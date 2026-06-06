import os
import logging
import secrets
import subprocess
import time
from pathlib import Path
from datetime import datetime
import re
import atexit
from functools import wraps

from flask import (
    Flask,
    Response,
    request,
    jsonify,
    render_template,
    redirect,
)
from flask_httpauth import HTTPBasicAuth
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash

import psycopg2

from lablink_allocator_service.get_config import get_config
from lablink_allocator_service.conf.structured_config import MISSING_SECRET
from lablink_allocator_service.database import PostgresqlDatabase
from lablink_allocator_service.utils.config_helpers import (
    get_allocator_url,
    is_self_signed_ssl,
    should_use_https,
)
from lablink_allocator_service.utils.sg_audit import SGAuditFailure
from lablink_allocator_service.scheduler import ScheduledDestructionService
from lablink_allocator_service.reboot import AutoRebootService
from lablink_allocator_service.client_session import RotationFailed
from lablink_allocator_service.signed_cookie import (
    sign,
    get_or_create_cookie_secret,
)
from lablink_allocator_service.providers.registry import get_provider
from lablink_allocator_service.secret_hash import hash_secret, verify_secret
from lablink_allocator_service.routes.desktop import bp as desktop_bp
from lablink_allocator_service.routes.internal_proxy_auth import (
    bp as internal_proxy_auth_bp,
)
from lablink_allocator_service.routes.registration import bp as registration_bp

app = Flask(__name__)


class _ProxyFixWhenTrusted:
    """ProxyFix gated by a runtime predicate.

    Trusts X-Forwarded-Proto/Host only when the predicate returns True.
    The HTTPS-on deployment is the only topology where nginx terminates
    TLS in front of Flask; without nginx (ssl.provider="none"), there is
    no trusted upstream and any client could spoof X-Forwarded-Proto
    https into the registration response's allocator_url. Gating makes
    that trust boundary explicit — and cheap to verify.

    The predicate is evaluated per request so tests can flip cfg.ssl
    without re-wrapping the WSGI stack.
    """

    def __init__(self, wsgi_app, *, trust_headers):
        self._raw = wsgi_app
        self._wrapped = ProxyFix(wsgi_app, x_proto=1, x_host=1)
        self._trust_headers = trust_headers

    def __call__(self, environ, start_response):
        if self._trust_headers():
            return self._wrapped(environ, start_response)
        return self._raw(environ, start_response)


# `cfg` is bound further down; the lambda resolves it at request time so
# monkeypatching main.cfg in tests takes effect without re-wrapping.
app.wsgi_app = _ProxyFixWhenTrusted(
    app.wsgi_app, trust_headers=lambda: should_use_https(cfg)
)
app.register_blueprint(desktop_bp)
app.register_blueprint(internal_proxy_auth_bp)
app.register_blueprint(registration_bp)
auth = HTTPBasicAuth()

# Define the terraform directory relative to this file (now inside the package)
TERRAFORM_DIR = (Path(__file__).parent / "terraform").resolve()

# Load the configuration
cfg = get_config()

# Provider is now driven by structured config (see PR D3). Defaults to "aws"
# for behavior parity with pre-D3 deployments.
app.config["LABLINK_PROVIDER"] = get_provider(
    cfg.provider,
    region=cfg.app.region,
    terraform_dir=str(TERRAFORM_DIR),
)

os.environ["DATABASE_URL"] = (
    f"postgresql://{cfg.db.user}:{cfg.db.password}@{cfg.db.host}:{cfg.db.port}/{cfg.db.dbname}"
)

# Validate that required secrets are configured
_missing = []
if cfg.app.admin_user == MISSING_SECRET:
    _missing.append("app.admin_user")
if cfg.app.admin_password == MISSING_SECRET:
    _missing.append("app.admin_password")
if _missing:
    raise SystemExit(
        f"FATAL: Required secrets not configured: {', '.join(_missing)}. "
        f"Set these in your config.yaml (injected from GitHub secrets in production)."
    )

# Initialize variables
users = {cfg.app.admin_user: generate_password_hash(cfg.app.admin_password)}
ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
allocator_ip = os.getenv("ALLOCATOR_PUBLIC_IP")
key_name = os.getenv("ALLOCATOR_KEY_NAME")
ENVIRONMENT = os.getenv("ENVIRONMENT", "prod").strip().lower().replace(" ", "-")
cloud_init_output_log_group = os.getenv("CLOUD_INIT_LOG_GROUP")

# Deployment register-token (machine registration): one per allocator process,
# re-injected via terraform on launch.
REGISTER_TOKEN = secrets.token_urlsafe(32)

# Deployment agent-control token: allocator→client-agent (:7070) control
# channel. Distinct from REGISTER_TOKEN (client→allocator join). Symmetric
# plaintext (allocator presents, agent verifies); per-process like
# REGISTER_TOKEN.
AGENT_TOKEN = secrets.token_urlsafe(32)

# Initialize the database connection
database = None

# Scheduler service (initialized in main())
scheduler_service = None

# Auto-reboot service (initialized in main())
reboot_service = None

# Startup timestamp for uptime tracking (set in main())
_startup_time: float | None = None


def init_database():
    """Initialize the database connection."""
    global database
    database = PostgresqlDatabase(
        dbname=cfg.db.dbname,
        user=cfg.db.user,
        password=cfg.db.password,
        host=cfg.db.host,
        port=cfg.db.port,
        table_name=cfg.db.table_name,
    )
    # Expose the underlying psycopg2 pool to blueprints (e.g. /desktop,
    # /internal/proxy_auth) that need a raw connection for the signed-cookie
    # helpers, without coupling them to the PostgresqlDatabase wrapper.
    app.config["DB_POOL"] = database._pool
    app.config["VM_TABLE_NAME"] = cfg.db.table_name
    # Persist the deployment register-token as an argon2 hash at rest
    # (SR-F14). Validation reads this back via settings (Option A).
    database.set_setting("register_token_hash", hash_secret(REGISTER_TOKEN))


# Set up logging
_log_level = (
    logging.DEBUG
    if cfg.environment in ("dev", "test", "ci-test")
    else logging.INFO
)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
logger.setLevel(_log_level)

# For deployments where the allocator can't provision hosts (BYO / manual
# provider), surface the register-token in the container logs so
# `lablink deploy` (compose mode) can extract it. AWS deployments get the
# token via the Terraform output file instead.
#
# Gate is the capability flag `can_provision_hosts`, not the provider
# *type* — keeps Spec §7 clean (no provider-type equality branches in core).
#
# IMPORTANT: the `key=value` format MUST be used so the CLI's
# `_extract_register_token` regex (`REGISTER_TOKEN\s*=\s*...`) matches.
# Don't change the format without updating the extractor.
if not app.config["LABLINK_PROVIDER"].can_provision_hosts:
    logger.info("REGISTER_TOKEN=%s", REGISTER_TOKEN)


@auth.verify_password
def verify_password(username, password):
    """Verify the username and password against the stored users.
    Args:
        username (str): The username to verify.
        password (str): The password to verify.
    Returns:
        str: The username if the credentials are valid, None otherwise.
    """
    if username in users and check_password_hash(users.get(username), password):
        return username



def require_client_secret(f):
    """Require a valid per-client secret Bearer token. The client row is
    resolved from the request's hostname field (`vm_id` for heartbeat,
    else `hostname`; falls back to a `hostname` route kwarg)."""

    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or invalid Authorization header."}), 401
        token = auth_header[7:]

        body = request.get_json(silent=True) or {}
        hostname = (
            body.get("vm_id")
            or body.get("hostname")
            or kwargs.get("hostname")
            or kwargs.get("client_id")
        )
        if not hostname:
            return jsonify({"error": "client identity required."}), 401

        stored = database.get_client_secret_hash(hostname)
        if not stored or not verify_secret(token, stored):
            return jsonify({"error": "Invalid client secret."}), 401
        return f(*args, **kwargs)

    return decorated


def notify_participants():
    """Trigger function to notify participant VMs."""
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cursor = conn.cursor()
    cursor.execute("LISTEN vm_updates;")
    conn.commit()


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/health", methods=["GET"])
def health_check():
    """Return structured readiness status."""
    checks = {
        "database": "ok" if database is not None else "not initialized",
        "scheduler": "ok" if scheduler_service is not None else "not initialized",
        "reboot_service": "ok" if reboot_service is not None else "not initialized",
    }

    all_ready = all(v == "ok" for v in checks.values())
    status = "healthy" if all_ready else "starting"
    code = 200 if all_ready else 503

    payload = {
        "status": status,
        "checks": checks,
    }

    if _startup_time is not None:
        payload["uptime_seconds"] = round(time.monotonic() - _startup_time, 1)

    return jsonify(payload), code


@app.route("/admin/create")
@auth.login_required
def create_instances():
    return render_template("create-instances.html")


@app.route("/admin")
@auth.login_required
def admin():
    provider = app.config["LABLINK_PROVIDER"]
    return render_template(
        "admin.html",
        can_provision_hosts=provider.can_provision_hosts,
        can_destroy_hosts=provider.can_destroy_hosts,
    )


@app.route("/admin/byo-onboarding")
@auth.login_required
def byo_onboarding():
    """Render the ready-to-copy `lablink client register` command for BYO clients.

    The register token rotates on each allocator restart, so this page is
    dynamic — re-render to get the current token. Behind admin Basic auth
    (same gate as the rest of /admin); no new privilege boundary.
    """
    return render_template(
        "byo-onboarding.html",
        allocator_url=request.host_url.rstrip("/"),
        register_token=REGISTER_TOKEN,
        show_insecure=is_self_signed_ssl(cfg),
    )


@app.route("/admin/instances")
@auth.login_required
def view_instances():
    instances = database.get_all_vms()
    return render_template("instances.html", instances=instances)


@app.route("/admin/instances/delete")
@auth.login_required
def delete_instances():
    return render_template("delete-instances.html")


@app.route("/api/request_vm", methods=["POST"])
def submit_vm_details():
    import uuid

    try:
        email = (request.form.get("email") or "").strip().lower()
        if not email:
            return render_template("index.html", error="Email is required.")

        # Idempotent rejoin: if this email already owns a running seat,
        # keep them on it and continue to prep a fresh browser session.
        existing = database.get_assigned_vm_for_email(email=email)
        if existing is not None and existing["status"] == "running":
            hostname = existing["hostname"]
        else:
            # Fresh assignment. assign_vm raises ValueError if no VM is
            # available; we treat that as 503 (no seats).
            try:
                database.assign_vm(email=email)
            except ValueError:
                logger.warning("Pool empty when '%s' asked for a seat", email)
                return render_template("no_seats.html"), 503
            re_lookup = database.get_assigned_vm_for_email(email=email)
            if re_lookup is None:
                # Shouldn't happen: assign_vm succeeded but lookup missed.
                logger.error(
                    "Assigned VM not visible to follow-up lookup for '%s'",
                    email,
                )
                return render_template("no_seats.html"), 503
            hostname = re_lookup["hostname"]

        # Mint per-session identifiers and rotate the VNC password on the
        # assigned client. RotationFailed → mark unhealthy and ask the
        # student to retry; the failed-VM recovery loop will pick it up.
        session_id = uuid.uuid4()
        browser_token = secrets.token_urlsafe(16)
        try:
            provider = app.config.get("LABLINK_PROVIDER") or get_provider(
                cfg.provider, region=cfg.app.region, terraform_dir=str(TERRAFORM_DIR)
            )
            provider.client_connectivity.prepare_browser_session(
                database=database,
                hostname=hostname,
                session_id=session_id,
                browser_token=browser_token,
                agent_token=AGENT_TOKEN,
            )
        except RotationFailed as exc:
            logger.warning(
                "Password rotation failed for '%s' on '%s': %s",
                email, hostname, exc,
            )
            # Release the seat so the student isn't permanently wedged
            # on the rotation_failed page: without this, the rejoin
            # branch at the top of this handler keeps matching the
            # same row (status is still 'running') and re-enters
            # prepare_browser_session, which keeps failing.
            try:
                database.update_health(hostname=hostname, healthy="Unhealthy")
                database.release_seat(hostname=hostname)
            except Exception:
                logger.exception("Could not mark '%s' unhealthy", hostname)
            return render_template("rotation_failed.html"), 503

        # Sign the session_id and set the cookie. Secure flag is decided
        # by whether the inbound request was https — front door
        # (ALB/Caddy/Cloudflare) sets X-Forwarded-Proto.
        conn = database._pool.getconn()
        try:
            secret = get_or_create_cookie_secret(conn)
        finally:
            database._pool.putconn(conn)

        signed = sign(str(session_id), secret=secret)
        resp = redirect("/desktop", code=303)
        is_https = request.headers.get("X-Forwarded-Proto") == "https"
        resp.set_cookie(
            "lablink_session", signed,
            httponly=True, samesite="Strict",
            secure=is_https, path="/",
        )
        return resp

    except Exception as e:
        logger.error("Error in submit_vm_details: %s", e, exc_info=True)
        return render_template(
            "index.html",
            error="An unexpected error occurred while processing your request. "
            "Please ask your instructor for help.",
        )


def _wants_json():
    """Return True if the client prefers a JSON response."""
    return request.accept_mimetypes.best == "application/json"


@app.route("/api/launch", methods=["POST"])
@auth.login_required
def launch():
    provider = app.config["LABLINK_PROVIDER"]
    if not provider.can_provision_hosts:
        error_msg = "Provider does not support host provisioning."
        if _wants_json():
            return jsonify({"status": "error", "error": error_msg}), 405
        return render_template("dashboard.html", error=error_msg), 405

    # Validate num_vms input (unchanged)
    try:
        num_vms_str = request.form.get("num_vms")
        if not num_vms_str:
            error_msg = "Number of VMs is required."
            if _wants_json():
                return jsonify({"status": "error", "error": error_msg}), 400
            return render_template("dashboard.html", error=error_msg)
        num_vms = int(num_vms_str)
        if num_vms <= 0:
            error_msg = "Number of VMs must be greater than 0."
            if _wants_json():
                return jsonify({"status": "error", "error": error_msg}), 400
            return render_template("dashboard.html", error=error_msg)
    except ValueError:
        error_msg = "Invalid number of VMs. Please enter a valid integer."
        if _wants_json():
            return jsonify({"status": "error", "error": error_msg}), 400
        return render_template("dashboard.html", error=error_msg)

    if not allocator_ip or not key_name:
        logger.error("Missing allocator outputs.")
        error_msg = "Allocator outputs not found."
        if _wants_json():
            return jsonify({"status": "error", "error": error_msg}), 500
        return render_template("dashboard.html", error=error_msg)

    total_vms = num_vms + database.get_row_count()
    allocator_url, scheme = get_allocator_url(cfg, allocator_ip)
    logger.info(f"Using allocator URL: {allocator_url} (protocol: {scheme})")

    spec = {
        "allocator_ip": allocator_ip,
        "allocator_url": allocator_url,
        "machine_type": cfg.machine.machine_type,
        "image_name": cfg.machine.image,
        "repository": cfg.machine.repository,
        "client_ami_id": cfg.machine.ami_id,
        "subject_software": cfg.machine.software,
        "resource_prefix": (
            f"{cfg.machine.software}-lablink-client-{ENVIRONMENT}"
        ),
        "cloud_init_output_log_group": cloud_init_output_log_group,
        "startup_on_error": cfg.startup_script.on_error,
        "agent_token": AGENT_TOKEN,
        "register_token": REGISTER_TOKEN,
        "environment": ENVIRONMENT,
        "bucket_name": cfg.bucket_name,
        "deployment_name": getattr(cfg, "deployment_name", "lablink"),
    }

    try:
        result = provider.provision_hosts(count=total_vms, spec=spec)
    except SGAuditFailure as exc:
        logger.error("SG audit refused the plan: %s", exc)
        error_msg = f"Security-group audit refused the plan: {exc}"
        if _wants_json():
            return jsonify({"status": "error", "error": error_msg}), 400
        return render_template("dashboard.html", error=error_msg), 400
    except subprocess.CalledProcessError as e:
        logger.error("Terraform failed: %s", e.stderr)
        clean_err = ANSI_ESCAPE.sub("", (e.stderr or "")).strip()
        error_msg = f"Terraform failed: {clean_err}"
        if _wants_json():
            return jsonify({"status": "error", "error": error_msg}), 500
        return render_template("dashboard.html", error=error_msg)
    except Exception as e:
        logger.error("Unexpected error during launch: %s", e)
        if _wants_json():
            return jsonify({"status": "error", "error": str(e)}), 500
        return render_template("dashboard.html", error=str(e))

    # Update DB with timings (route-owned; provider returned them)
    for hostname, times in result.timings.items():
        start_time = datetime.fromisoformat(
            times["start_time"].replace("Z", "+00:00")
        )
        end_time = datetime.fromisoformat(
            times["end_time"].replace("Z", "+00:00")
        )
        database.update_terraform_timing(
            hostname=hostname,
            per_instance_seconds=float(times["seconds"]),
            per_instance_start_time=start_time,
            per_instance_end_time=end_time,
        )

    # Success response — match the pre-refactor shape EXACTLY
    if _wants_json():
        return jsonify({
            "status": "success",
            "output": result.apply_stdout,
        })
    return render_template("dashboard.html", output=result.apply_stdout)


@app.route("/destroy", methods=["POST"])
@auth.login_required
def destroy():
    provider = app.config["LABLINK_PROVIDER"]
    if not provider.can_destroy_hosts:
        error_msg = "Provider does not support host destruction."
        if _wants_json():
            return jsonify({"status": "error", "error": error_msg}), 405
        return render_template("delete-dashboard.html", error=error_msg), 405

    # Seal any open session-metrics rows before tearing down VMs, so the
    # final sessions get a duration even though the client agents are about
    # to be killed. Best-effort: never block destroy on a seal failure.
    try:
        sealed = database.bulk_seal_session_metrics()
        logger.info("Sealed %d session-metrics rows before destroy", sealed)
    except Exception as e:
        # Sealing is best-effort; do not block the destroy.
        logger.warning("Could not bulk-seal session metrics: %s", e)

    # destroy_hosts ignores the handles arg (terraform destroy operates on
    # the whole workspace); skip the list_hosts() call.
    try:
        result = provider.destroy_hosts([])
    except FileNotFoundError as e:
        # No terraform.runtime.tfvars → no client VMs were ever launched.
        msg = str(e)
        logger.info(msg)
        if _wants_json():
            return jsonify({"status": "error", "error": msg}), 404
        return render_template("delete-dashboard.html", error=msg), 404
    except subprocess.CalledProcessError as e:
        logger.error(f"Error during Terraform destroy: {e}")
        error_output = ANSI_ESCAPE.sub("", e.stderr or e.stdout or "")
        if _wants_json():
            return jsonify({"status": "error", "error": error_output}), 500
        return render_template("delete-dashboard.html", error=error_output)

    # Clear the database after successful destroy.
    logger.debug("Clearing the database...")
    database.clear_database()
    logger.debug("Database cleared successfully.")

    if _wants_json():
        return jsonify({"status": "success", "output": result.stdout})
    return render_template("delete-dashboard.html", output=result.stdout)


@app.route("/api/unassigned_vms_count", methods=["GET"])
def get_unassigned_instance_counts():
    """Get the counts of all instance types."""
    instance_counts = len(database.get_unassigned_vms())
    return jsonify(count=instance_counts), 200


@app.route("/api/update_inuse_status", methods=["POST"])
@require_client_secret
def update_inuse_status():
    """Update the in-use status of a VM."""
    data = request.get_json()
    hostname = data.get("hostname")
    in_use = data.get("status")

    logger.debug(f"Updating in-use status for {hostname} to {in_use}")

    if not hostname:
        return jsonify({"error": "Hostname is required."}), 400

    try:
        database.update_vm_in_use(hostname=hostname, in_use=in_use)
        return jsonify({"message": "In-use status updated successfully."}), 200
    except Exception as e:
        logger.error(f"Error updating in-use status: {e}")
        return jsonify({"error": "Failed to update in-use status."}), 500


@app.route("/api/gpu_health", methods=["POST"])
@require_client_secret
def update_gpu_health():
    """Check the health of the GPU."""
    data = request.get_json()
    gpu_status = data.get("gpu_status")
    hostname = data.get("hostname")
    if gpu_status is None or hostname is None:
        return jsonify({"error": "GPU status and hostname are required."}), 400

    try:
        database.touch_last_seen(hostname=hostname)
        database.update_health(hostname=hostname, healthy=gpu_status)
        logger.debug(f"Updated GPU health status for {hostname} to {gpu_status}")
        return jsonify({"message": "GPU health status updated successfully."}), 200
    except Exception as e:
        logger.error(f"Error updating GPU health status: {e}")
        return jsonify({"error": "Failed to update GPU health status."}), 500


@app.route("/api/heartbeat", methods=["POST"])
@require_client_secret
def heartbeat():
    """Record a client-VM liveness heartbeat."""
    data = request.get_json() or {}
    hostname = data.get("vm_id")
    if not hostname:
        return jsonify({"error": "vm_id is required."}), 400

    boot_id = data.get("boot_id")
    disk_free_pct = data.get("disk_free_pct")

    try:
        ok = database.record_heartbeat(
            hostname=hostname,
            boot_id=boot_id,
            disk_free_pct=disk_free_pct,
        )
        if not ok:
            return jsonify({"error": "Unknown hostname."}), 404
        return jsonify({"ok": True}), 200
    except Exception as e:
        logger.error(f"Error recording heartbeat for {hostname}: {e}")
        return jsonify({"error": "Failed to record heartbeat."}), 500


@app.route("/api/vm-status", methods=["POST"])
@require_client_secret
def update_vm_status():
    try:
        data = request.get_json()
        hostname = data.get("hostname")
        status = data.get("status")

        if not hostname or status is None:
            return jsonify({"error": "Hostname and status are required."}), 400

        database.touch_last_seen(hostname=hostname)
        database.update_vm_status(hostname=hostname, status=status)

        return jsonify({"message": "VM status updated successfully."}), 200
    except Exception as e:
        logger.error(f"Error updating VM status: {e}")
        return jsonify({"error": "Failed to update VM status."}), 500


@app.route("/api/vm-status", methods=["GET"])
@auth.login_required
def get_all_vm_status():
    try:
        vm_status = database.get_all_vm_status()
        if not vm_status:
            return jsonify({"error": "No VMs found."}), 404

        return jsonify(vm_status), 200
    except Exception as e:
        logger.error(f"Error getting all VM status: {e}")
        return jsonify({"error": "Failed to get VM status."}), 500


@app.route("/api/vm-logs/<hostname>", methods=["POST"])
@require_client_secret
def receive_vm_logs(hostname):
    try:
        data = request.get_json()
        log_group = data.get("log_group")
        messages = data.get("messages", [])

        if not log_group or not messages:
            return (
                jsonify({"error": "Log group and messages are required."}),
                400,
            )

        # Check if the VM exists in the database
        if not database.vm_exists(hostname):
            logger.error(f"VM with hostname {hostname} does not exist.")
            return jsonify({"error": "VM not found."}), 404

        logger.debug(
            f"Received logs for {log_group}/{hostname}: {len(messages)} messages"
        )

        # Strip ANSI escape codes and drop empty lines
        messages = [ANSI_ESCAPE.sub("", m) for m in messages]
        messages = [m for m in messages if m.strip()]

        if not messages:
            return jsonify({"message": "No log messages after filtering."}), 200

        # Determine log type from log_group
        log_type = "docker" if log_group.endswith("-docker") else "cloud_init"

        # Save the logs to the database atomically (cap at 1MB per log type)
        MAX_LOG_SIZE = 1 * 1024 * 1024  # 1MB
        new_logs = "\n".join(messages)
        database.append_logs_by_hostname(
            hostname=hostname,
            new_logs=new_logs,
            log_type=log_type,
            max_size=MAX_LOG_SIZE,
        )

        return jsonify({"message": "VM logs posted successfully."}), 200
    except Exception as e:
        logger.error(f"Error receiving VM logs: {e}")
        return jsonify({"error": "Failed to post VM logs."}), 500


@app.route("/api/vm-logs/<hostname>", methods=["GET"])
@auth.login_required
def get_vm_logs_by_hostname(hostname):
    try:
        if not database.vm_exists(hostname):
            logger.error(f"VM with hostname {hostname} not found.")
            return jsonify({"error": "VM not found."}), 404

        # If the logs are empty but the vm is initializing, return a 503 status
        logs_data = database.get_vm_logs(hostname=hostname)
        status = database.get_status_by_hostname(hostname)
        if logs_data is None and status == "initializing":
            return jsonify({"error": "VM is initializing."}), 503

        cloud_init_logs = (logs_data or {}).get("cloud_init_logs")
        docker_logs = (logs_data or {}).get("docker_logs")

        return jsonify({
            "hostname": hostname,
            "cloud_init_logs": cloud_init_logs,
            "docker_logs": docker_logs,
            "logs": "\n".join(filter(None, [cloud_init_logs, docker_logs])) or None,
        }), 200
    except Exception as e:
        logger.error(f"Error getting VM logs: {e}")
        return jsonify({"error": "Failed to get VM logs."}), 500


@app.route("/admin/logs/<hostname>", methods=["GET"])
@auth.login_required
def get_vm_logs(hostname):
    """Get the logs for a specific VM."""
    logger.debug(f"Fetching logs for VM: {hostname}")
    if not database.vm_exists(hostname=hostname):
        logger.error(f"VM with hostname {hostname} not found.")
        return jsonify({"error": "VM not found."}), 404
    # Non-AWS providers (manual/BYO) have no cloud-init concept; the
    # template hides that section when provider != "aws".
    return render_template(
        "instance-logs.html",
        hostname=hostname,
        provider=cfg.provider,
    )


@app.route("/api/vm-metrics/<hostname>", methods=["POST"])
@require_client_secret
def receive_vm_metrics(hostname):
    """Receive and store VM Cloud init metrics."""
    try:
        data = request.get_json()

        if not database.vm_exists(hostname=hostname):
            logger.error(f"VM with hostname {hostname} does not exist.")
            return jsonify({"error": "VM not found."}), 404

        database.touch_last_seen(hostname=hostname)
        # Update VM metrics and calculate total startup time atomically
        # This combines two database operations into one for better performance
        database.update_vm_metrics_atomic(hostname=hostname, metrics=data)

        logger.debug(f"Received metrics for {hostname}")
        return jsonify({"message": "VM metrics posted successfully."}), 200

    except Exception as e:
        logger.error(f"Error receiving VM metrics for {hostname}: {e}", exc_info=True)
        return jsonify({"error": "Failed to post VM metrics."}), 500


@app.route("/api/session-metrics/<hostname>", methods=["POST"])
@require_client_secret
def post_session_metrics(hostname):
    """Receive a Tier 1 monitoring summary push from a client VM."""
    try:
        data = request.get_json(silent=True) or {}
        if "counters" not in data:
            return jsonify({"error": "Missing 'counters' in payload."}), 400
        database.update_session_metrics(hostname=hostname, payload=data)
        return jsonify({"message": "Session metrics updated."}), 200
    except LookupError:
        return jsonify({"error": "VM not found."}), 404
    except ValueError as e:
        # Sealed row — refuse update.
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        logger.error(
            f"Error in /api/session-metrics/{hostname}: {e}", exc_info=True
        )
        return jsonify({"error": "Failed to update session metrics."}), 500


@app.route("/api/export-metrics", methods=["GET"])
@auth.login_required
def export_metrics():
    """Export VM metrics data as JSON."""
    try:
        include_logs = request.args.get("include_logs", "false").lower() == "true"
        vms = database.get_all_vms_for_export(include_logs=include_logs)

        # Serialize datetime objects to ISO format strings
        for vm in vms:
            for key, value in vm.items():
                if hasattr(value, "isoformat"):
                    vm[key] = value.isoformat()

        return jsonify({"vms": vms, "count": len(vms)}), 200
    except Exception as e:
        logger.error(f"Error exporting metrics: {e}")
        return jsonify({"error": "Failed to export metrics."}), 500


@app.route("/api/schedule-destruction", methods=["POST"])
@auth.login_required
def create_scheduled_destruction() -> Response | tuple[Response, int]:
    """
    Create a new scheduled destruction.

    Request JSON:
    {
        "schedule_name": "Friday Tutorial End",
        "destruction_time": "2025-12-05T17:30:00Z",
        "recurrence_rule": null  // or "FREQ=WEEKLY;BYDAY=FR;BYHOUR=17;BYMINUTE=30"
    }

    Returns:
        Response: JSON with schedule_id and success status, or error with status code.
    """
    from datetime import datetime

    data = request.get_json()

    # Validation
    if not data.get("schedule_name"):
        return jsonify({"success": False, "message": "schedule_name is required"}), 400

    if not data.get("destruction_time"):
        return jsonify(
            {"success": False, "message": "destruction_time is required"}
        ), 400

    try:
        destruction_time = datetime.fromisoformat(
            data["destruction_time"].replace("Z", "+00:00")
        )

        # Ensure time is in future
        if destruction_time <= datetime.now(destruction_time.tzinfo):
            return jsonify(
                {"success": False, "message": "destruction_time must be in the future"}
            ), 400

        if scheduler_service is None:
            return jsonify(
                {"success": False, "message": "Scheduler service not initialized"}
            ), 500

        try:
            schedule_id = scheduler_service.schedule_destruction(
                schedule_name=data["schedule_name"],
                destruction_time=destruction_time,
                recurrence_rule=data.get("recurrence_rule"),
                created_by=auth.current_user(),
                notification_enabled=data.get("notification_enabled", False),
                notification_hours_before=data.get("notification_hours_before", 1),
            )
        except ValueError as e:
            # Duplicate schedule name (from database unique constraint)
            return jsonify({"success": False, "message": str(e)}), 409
        except RuntimeError as e:
            # Database or scheduler error
            logger.error(f"Failed to create scheduled destruction: {e}")
            return jsonify({"success": False, "message": str(e)}), 500

        return jsonify(
            {
                "success": True,
                "schedule_id": schedule_id,
                "message": "Scheduled destruction created successfully",
            }
        ), 200

    except ValueError as e:
        return jsonify(
            {"success": False, "message": f"Invalid destruction_time format: {str(e)}"}
        ), 400
    except Exception as e:
        logger.error(f"Failed to create scheduled destruction: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/schedule-destruction/<int:schedule_id>", methods=["GET"])
@auth.login_required
def get_scheduled_destruction(schedule_id: int):
    """Get details of a scheduled destruction."""

    schedule = database.get_scheduled_destruction(schedule_id)

    if not schedule:
        return jsonify({"success": False, "message": "Schedule not found"}), 404

    return jsonify({"success": True, "schedule": schedule})


@app.route("/api/schedule-destruction", methods=["GET"])
@auth.login_required
def list_scheduled_destructions() -> Response | tuple[Response, int]:
    """
    List all scheduled destructions.

    Query parameters:
        status (optional): Filter by status (scheduled, executing, completed,
            failed, cancelled)

    Returns:
        Response: JSON with list of schedules, or error with status code.
    """

    status_filter = request.args.get("status")

    if status_filter and status_filter not in [
        "scheduled",
        "executing",
        "completed",
        "failed",
        "cancelled",
    ]:
        return jsonify(
            {"success": False, "message": f"Invalid status filter: {status_filter}"}
        ), 400

    schedules = database.get_all_scheduled_destructions(status=status_filter)

    return jsonify({"success": True, "schedules": schedules, "count": len(schedules)})


@app.route("/api/schedule-destruction/<int:schedule_id>", methods=["DELETE"])
@auth.login_required
def cancel_scheduled_destruction(schedule_id: int):
    """Cancel a scheduled destruction."""

    # Check if schedule exists
    schedule = database.get_scheduled_destruction(schedule_id)
    if not schedule:
        return jsonify({"success": False, "message": "Schedule not found"}), 404

    # Check if already cancelled or completed
    if schedule["status"] in ["cancelled", "completed"]:
        return jsonify(
            {
                "success": False,
                "message": f"Cannot cancel schedule with status '{schedule['status']}'",
            }
        ), 400

    if scheduler_service is None:
        return jsonify(
            {"success": False, "message": "Scheduler service not initialized"}
        ), 500

    try:
        scheduler_service.cancel_scheduled_destruction(schedule_id)

        return jsonify(
            {
                "success": True,
                "message": (
                    f"Scheduled destruction {schedule_id} cancelled successfully"
                ),
            }
        )

    except Exception as e:
        logger.error(f"Failed to cancel scheduled destruction: {e}")
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/admin/scheduled-destruction", methods=["GET"])
@auth.login_required
def scheduled_destruction_page():
    """Render scheduled destruction management page."""
    return render_template("scheduled-destruction.html")


def main():
    """Main entry point for the allocator service."""
    global scheduler_service, reboot_service, _startup_time

    try:
        _startup_time = time.monotonic()
        with app.app_context():
            init_database()

        # Initialize scheduler service
        logger.info("Initializing scheduler service...")
        db_url = (
            f"postgresql://{cfg.db.user}:{cfg.db.password}"
            f"@{cfg.db.host}:{cfg.db.port}/{cfg.db.dbname}"
        )
        scheduler_service = ScheduledDestructionService(
            database=database,
            db_url=db_url,
        )
        scheduler_service.start()
        atexit.register(scheduler_service.stop)
        logger.info("Scheduler service started successfully")

        # Initialize auto-reboot service
        logger.info("Initializing auto-reboot service...")
        reboot_service = AutoRebootService(
            database=database,
            region=cfg.app.region,
            terraform_dir=str(TERRAFORM_DIR),
            provider=app.config.get("LABLINK_PROVIDER"),
        )
        reboot_service.start()
        atexit.register(reboot_service.stop)
        logger.info("Auto-reboot service started successfully")

        # Terraform initialization — gated on the provider's capability flag
        # (mirrors the policy at module top: branch on capability, not type).
        # Manual/BYO providers don't provision hosts, so `terraform init` is
        # irrelevant and the binary may not even be present in the image.
        provider = app.config["LABLINK_PROVIDER"]
        if not provider.can_provision_hosts:
            logger.info(
                "Skipping terraform init: provider %s does not provision hosts.",
                getattr(provider, "name", type(provider).__name__),
            )
        elif not (TERRAFORM_DIR / "terraform.runtime.tfvars").exists():
            logger.info("Initializing Terraform...")
            if ENVIRONMENT not in ["prod", "test", "ci-test"]:
                (TERRAFORM_DIR / "backend.tf").unlink(missing_ok=True)
                subprocess.run(
                    ["terraform", "init"],
                    cwd=TERRAFORM_DIR,
                    check=True,
                )
            else:
                # Use bucket_name from config for client VM terraform state
                default_bucket = "tf-state-lablink-allocator-bucket"
                bucket_name = (
                    cfg.bucket_name if hasattr(cfg, "bucket_name") else default_bucket
                )
                # Derive deployment_name for state key scoping
                deployment_name = (
                    cfg.deployment_name
                    if hasattr(cfg, "deployment_name") and cfg.deployment_name
                    else "lablink"
                )
                state_key = f"{deployment_name}/{ENVIRONMENT}/client/terraform.tfstate"
                logger.info(
                    f"Initializing Terraform with S3 backend: {bucket_name} "
                    f"(key: {state_key})"
                )
                subprocess.run(
                    [
                        "terraform",
                        "init",
                        f"-backend-config=backend-client-{ENVIRONMENT}.hcl",
                        f"-backend-config=key={state_key}",
                        f"-backend-config=bucket={bucket_name}",
                        f"-backend-config=region={cfg.app.region}",
                    ],
                    cwd=TERRAFORM_DIR,
                    check=True,
                )

        logger.info("Auto-generated API token for machine-to-machine auth")
        logger.info("Starting Flask application...")
        flask_host = os.environ.get("FLASK_HOST", "127.0.0.1")
        flask_port = int(os.environ.get("FLASK_PORT", "8000"))
        app.run(host=flask_host, port=flask_port, threaded=True)

    except Exception as e:
        logger.error(f"Failed to start allocator service: {e}", exc_info=True)

        # Clean up services if they were initialized
        if reboot_service is not None:
            try:
                logger.info("Stopping auto-reboot service due to startup failure...")
                reboot_service.stop()
            except Exception as cleanup_error:
                logger.error(
                    f"Error stopping reboot service during cleanup: {cleanup_error}"
                )

        if scheduler_service is not None:
            try:
                logger.info("Stopping scheduler service due to startup failure...")
                scheduler_service.stop()
            except Exception as cleanup_error:
                logger.error(
                    f"Error stopping scheduler during cleanup: {cleanup_error}"
                )

        # Re-raise the exception to exit with error code
        raise


if __name__ == "__main__":
    main()
