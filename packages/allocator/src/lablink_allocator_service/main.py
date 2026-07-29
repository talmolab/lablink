import os
import logging
import secrets
import subprocess
import time
from pathlib import Path
import atexit

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash

from lablink_allocator_service.get_config import get_config
from lablink_allocator_service.conf.structured_config import MISSING_SECRET
from lablink_allocator_service.db.vms import VmDatabase
from lablink_allocator_service.db.schedules import ScheduleDatabase
from lablink_allocator_service.db.metrics import MetricsDatabase
from lablink_allocator_service.utils.config_helpers import should_use_https
from lablink_allocator_service.scheduler import ScheduledDestructionService
from lablink_allocator_service.reboot import AutoRebootService
from lablink_allocator_service.admin_session_expiry import AdminSessionExpiryService
from lablink_allocator_service.operations import OperationsWorker
from lablink_allocator_service.db.operations import OperationsDatabase
from lablink_allocator_service.providers.registry import get_provider
from lablink_allocator_service.secret_hash import hash_secret
from lablink_allocator_service.routes.admin_pages import bp as admin_pages_bp
from lablink_allocator_service.routes.admin_sessions import (
    bp as admin_sessions_bp,
)
from lablink_allocator_service.routes.desktop import bp as desktop_bp
from lablink_allocator_service.routes.health import bp as health_bp
from lablink_allocator_service.routes.internal_proxy_auth import (
    bp as internal_proxy_auth_bp,
)
from lablink_allocator_service.routes.metrics import bp as metrics_bp
from lablink_allocator_service.routes.provisioning import (
    bp as provisioning_bp,
)
from lablink_allocator_service.routes.public import bp as public_bp
from lablink_allocator_service.routes.registration import bp as registration_bp
from lablink_allocator_service.routes.schedules import bp as schedules_bp
from lablink_allocator_service.routes.vm_telemetry import bp as vm_telemetry_bp

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
app.register_blueprint(admin_pages_bp)
app.register_blueprint(admin_sessions_bp)
app.register_blueprint(desktop_bp)
app.register_blueprint(health_bp)
app.register_blueprint(internal_proxy_auth_bp)
app.register_blueprint(metrics_bp)
app.register_blueprint(provisioning_bp)
app.register_blueprint(public_bp)
app.register_blueprint(registration_bp)
app.register_blueprint(schedules_bp)
app.register_blueprint(vm_telemetry_bp)

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
    connectivity=cfg.manual.connectivity,
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

# Scheduled-destructions query layer (initialized in init_database()).
schedule_db = None

# Session-metrics query layer (initialized in init_database()).
metrics_db = None

# Scheduler service (initialized in main())
scheduler_service = None

# Auto-reboot service (initialized in main())
reboot_service = None

# Admin-session expiry service (initialized in main())
admin_session_expiry_service = None

# Operations worker for on-demand apply/destroy jobs (initialized in
# main()). Unlike the other three services, this has no persistent
# background thread/loop of its own — start() just runs a one-time
# startup sweep, and each submitted job gets its own short-lived thread.
# There is deliberately no operations_worker.stop()/atexit registration
# to match: there is no loop to join.
operations_worker = None

# Operations-table query layer (initialized in main()), promoted to a
# module global alongside operations_worker so routes can read job status
# directly (list/get/in-progress) without going through the worker, which
# only exposes submit()/start().
operations_db = None

# Startup timestamp for uptime tracking (set in main())
_startup_time: float | None = None


def init_database():
    """Initialize the database connection."""
    global database
    database = VmDatabase(
        dbname=cfg.db.dbname,
        user=cfg.db.user,
        password=cfg.db.password,
        host=cfg.db.host,
        port=cfg.db.port,
        table_name=cfg.db.table_name,
    )
    global schedule_db
    schedule_db = ScheduleDatabase(pool=database.pool)
    global metrics_db
    metrics_db = MetricsDatabase(pool=database.pool, table_name=cfg.db.table_name)
    # Expose the underlying psycopg2 pool to blueprints (e.g. /desktop,
    # /internal/proxy_auth) that need a raw connection for the signed-cookie
    # helpers, without coupling them to the VmDatabase wrapper.
    app.config["DB_POOL"] = database._pool
    app.config["VM_TABLE_NAME"] = cfg.db.table_name
    # Persist the deployment register-token as an argon2 hash at rest
    # (SR-F14). Validation reads this back via settings (Option A).
    database.set_setting("register_token_hash", hash_secret(REGISTER_TOKEN))


# Set up logging. Root stays at INFO as the floor for third-party loggers
# (botocore, paramiko, urllib3); only this package follows _log_level.
_log_level = (
    logging.DEBUG
    if cfg.environment in ("dev", "test", "ci-test")
    else logging.INFO
)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("lablink_allocator_service").setLevel(_log_level)

logger = logging.getLogger(__name__)

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


def main():
    """Main entry point for the allocator service."""
    global scheduler_service, reboot_service, admin_session_expiry_service
    global operations_worker, operations_db
    global _startup_time

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
            schedule_db=schedule_db,
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

        # Initialize admin-session expiry sweep
        logger.info("Initializing admin-session expiry service...")
        admin_session_expiry_service = AdminSessionExpiryService(
            database=database,
            timeout_minutes=cfg.app.admin_session_timeout_minutes,
        )
        admin_session_expiry_service.start()
        atexit.register(admin_session_expiry_service.stop)
        logger.info("Admin-session expiry service started successfully")

        # Initialize operations worker (on-demand apply/destroy jobs).
        # No atexit registration: see the module-level comment on
        # operations_worker — there's no background loop to stop.
        logger.info("Initializing operations worker...")
        operations_db = OperationsDatabase(pool=database.pool)
        operations_worker = OperationsWorker(database=operations_db)
        operations_worker.start()
        logger.info("Operations worker started successfully")

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

        if admin_session_expiry_service is not None:
            try:
                logger.info(
                    "Stopping admin-session expiry service due to startup failure..."
                )
                admin_session_expiry_service.stop()
            except Exception as cleanup_error:
                logger.error(
                    f"Error stopping admin-session expiry service during "
                    f"cleanup: {cleanup_error}"
                )

        # Re-raise the exception to exit with error code
        raise


if __name__ == "__main__":
    main()
