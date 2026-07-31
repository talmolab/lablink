"""POST /api/v1/clients/register, GET /api/v1/clients/<id>/status, and
POST /api/overlay-hostname (a mesh-overlay client correcting the overlay
hostname it was recorded under — see report_overlay_hostname).

Lazy-imports `main` inside views to avoid the module-load import cycle
(main imports this blueprint at startup). Mirrors the rationale behind
routes/desktop.py using current_app instead of importing main.
"""
from __future__ import annotations

import base64
from datetime import datetime
import psycopg2
import re
import secrets

from flask import Blueprint, current_app, jsonify, request

from lablink_allocator_service.auth import auth, require_client_secret
from lablink_allocator_service.providers.registry import get_provider
from lablink_allocator_service.secret_hash import (
    REGISTER_TOKEN_SUBJECT,
    hash_secret,
    verify_secret_cached,
)
from lablink_allocator_service.utils.config_helpers import canonical_base_url

bp = Blueprint("registration", __name__)

# A registering client's self-declared hostname becomes its client_id, which
# is the DB primary key AND (under reverse_tunnel) is interpolated into a
# generated config file and a filesystem path. Constrain it here, at the
# boundary, so nothing downstream has to trust it; tunnel_manager re-checks
# the same shape on its own as defense in depth.
_VALID_HOSTNAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$")


@bp.route("/api/v1/clients/register", methods=["POST"])
def register_client():
    from lablink_allocator_service import main

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "registration rejected"}), 401
    token = auth_header[7:]

    stored = main.database.get_setting("register_token_hash")
    if not stored or not verify_secret_cached(
        REGISTER_TOKEN_SUBJECT, token, stored
    ):
        return jsonify({"error": "registration rejected"}), 401

    body = request.get_json(silent=True) or {}
    hostname = body.get("hostname")
    machine_identity = body.get("machine_identity")
    if not hostname or not machine_identity:
        return jsonify({"error": "hostname and machine_identity required."}), 400
    if not isinstance(hostname, str) or not _VALID_HOSTNAME.fullmatch(hostname):
        return jsonify({
            "error": (
                "hostname must start with a letter or digit and contain only "
                "letters, digits, dots, dashes and underscores (max 253 "
                "characters)."
            )
        }), 400

    provider = body.get("provider", "aws")
    provider_metadata = body.get("provider_metadata") or {}

    prov = current_app.config.get("LABLINK_PROVIDER") or get_provider(
        main.cfg.get("provider", None),
        region=main.cfg.app.region,
        terraform_dir=str(main.TERRAFORM_DIR),
        connectivity=main.cfg.manual.connectivity,
    )

    # Manual/BYO clients pick their provider_metadata shape based on which
    # CLI flag they used (--lan-ip auto-detect vs --overlay-hostname). That
    # shape must match this deployment's configured connectivity strategy,
    # or the client silently registers under the wrong byte-path -- e.g. a
    # real-BYO lan_ip registration against a mesh_overlay allocator has the
    # browser dial the client's private LAN IP directly, which is
    # unreachable off that LAN. Caught here, at registration time, instead
    # of failing opaquely at session-assignment time.
    if provider == "manual":
        expects_overlay = prov.client_connectivity.name == "mesh_overlay"
        has_overlay = "overlay_hostname" in provider_metadata
        if expects_overlay and not has_overlay:
            return jsonify({
                "error": (
                    "This allocator is configured for mesh_overlay "
                    "connectivity -- register with --overlay-hostname "
                    "and --tailscale-authkey."
                )
            }), 400
        if not expects_overlay and has_overlay:
            return jsonify({
                "error": (
                    "This allocator is configured for lan_direct "
                    "connectivity -- --overlay-hostname is not applicable "
                    "here; omit it and let --lan-ip auto-detect."
                )
            }), 400

        # Same shape as the mesh_overlay check above: a reverse_tunnel
        # registration (--tunnel) against a non-tunnel allocator, or a
        # plain registration against a tunnel allocator, must be rejected
        # at registration time rather than failing opaquely later.
        expects_tunnel = prov.client_connectivity.name == "reverse_tunnel"
        has_tunnel = provider_metadata.get("reverse_tunnel") is True
        if expects_tunnel and not has_tunnel:
            return jsonify({
                "error": (
                    "This allocator is configured for reverse_tunnel "
                    "connectivity -- register with --tunnel."
                )
            }), 400
        if not expects_tunnel and has_tunnel:
            return jsonify({
                "error": (
                    "This allocator is not configured for reverse_tunnel "
                    "connectivity -- --tunnel is not applicable here."
                )
            }), 400

    client_secret = secrets.token_urlsafe(32)

    # Reverse-tunnel clients need two allocator-owned values minted before
    # the row is written: a loopback alias (the address nginx will dial) and
    # a path prefix identifying this client at the tunnel endpoint.
    tunnel_alias_octet = None
    tunnel_prefix = None
    if provider == "manual" and provider_metadata.get("reverse_tunnel") is True:
        from lablink_allocator_service import tunnel_manager

        tunnel_alias_octet = main.database.allocate_tunnel_alias_octet()
        # Range-check BEFORE writing the row: allocate_tunnel_alias_octet
        # never recycles, so a deployment can exhaust it (see its
        # docstring), and authorize_client would raise ValueError on an
        # out-of-range octet -- but only after register_client already
        # inserted the row, which would surface as an unhandled 500.
        if not tunnel_manager.is_valid_alias_octet(tunnel_alias_octet):
            return jsonify({
                "error": (
                    "This deployment has run out of reverse-tunnel "
                    "loopback aliases; no more clients can register."
                )
            }), 503
        tunnel_prefix = tunnel_manager.path_prefix(hostname, client_secret)
        provider_metadata = {
            **provider_metadata,
            "tunnel_alias_octet": tunnel_alias_octet,
            "tunnel_path_prefix": tunnel_prefix,
        }

    try:
        client_id = main.database.register_client(
            hostname=hostname,
            machine_identity=machine_identity,
            provider=provider,
            endpoint_url=body.get("endpoint_url"),
            provider_metadata=provider_metadata,
            gpu_present=body.get("gpu_present"),
            gpu_model=body.get("gpu_model"),
            client_secret_hash=hash_secret(client_secret),
        )
    except psycopg2.IntegrityError:
        return jsonify({"error": "registration conflict"}), 409
    if client_id is None:
        return jsonify({"error": "registration conflict"}), 409

    if tunnel_prefix is not None:
        from lablink_allocator_service import tunnel_manager

        # Authorize AFTER the row exists: the restrictions file is what lets
        # this client bind its alias, and it must never name an alias no row
        # claims. Re-registration overwrites the client's single rule, so a
        # new alias/prefix cannot leave the old one authorized.
        tunnel_manager.authorize_client(
            client_id=client_id, alias_octet=tunnel_alias_octet,
            prefix=tunnel_prefix,
        )

    allocator_url = canonical_base_url(request)
    # cfg.machine.repository is the tutorial-repo-to-clone URL (shipped to
    # the AWS path as spec["repository"] -> TUTORIAL_REPO_TO_CLONE in
    # client/start.sh) — unrelated to the docker image reference. The AWS
    # path already uses cfg.machine.image verbatim (spec["image_name"]);
    # match that here instead of prefixing repository onto it.
    client_image = main.cfg.machine.image
    jm = prov.client_connectivity.make_join_material(
        allocator_url=allocator_url,
        client_image=client_image,
        register_token=token,
    )

    # Ship the custom startup script to the client. BYO clients (manual
    # provider) have no other channel to receive it — the AWS path bakes
    # it into user_data, but `lablink client register` is the only
    # handshake the BYO box gets. Convention: the CLI stages the file at
    # /config/custom-startup.sh in both the AWS deploy dir and the manual
    # compose dir, so the path is the same regardless of provider.
    startup_b64 = ""
    if main.cfg.startup_script.enabled:
        script_path = "/config/custom-startup.sh"
        try:
            with open(script_path, "rb") as f:
                content = f.read()
            if content:
                startup_b64 = base64.b64encode(content).decode("ascii")
        except FileNotFoundError:
            current_app.logger.warning(
                "startup_script.enabled=true but %s not found", script_path
            )

    # Ship the Tier 1 monitoring block verbatim so the client's start.sh
    # can write it to /tmp/lablink-monitoring.json and gate the agent
    # launch on `enabled`. Lists are copied to plain Python via OmegaConf
    # so jsonify doesn't choke on ListConfig/DictConfig.
    monitoring = {
        "enabled": bool(main.cfg.monitoring.enabled),
        "subject_window_patterns": list(
            main.cfg.monitoring.subject_window_patterns or []
        ),
        "process_allowlist": list(main.cfg.monitoring.process_allowlist),
        "watch_dir": main.cfg.monitoring.watch_dir,
        "sample_interval_seconds": main.cfg.monitoring.sample_interval_seconds,
        "push_interval_seconds": main.cfg.monitoring.push_interval_seconds,
    }

    # cfg.machine settings the AWS path delivers as `docker run -e` flags
    # in terraform/user_data.sh. The register response is the manual/BYO
    # path's only equivalent channel, so ship them here and let the CLI
    # write them into the client's env file under the same names
    # client/start.sh already reads (lablink#405). `repository` is
    # Optional and normalized to "" — a JSON null would round-trip through
    # the CLI's env file as the literal string "None" and start.sh's `-n`
    # check would pass, making it `git clone None`.
    repository = main.cfg.machine.repository or ""
    subject_software = main.cfg.machine.software or ""

    response = dict(
        client_id=client_id,
        client_secret=client_secret,
        agent_token=main.AGENT_TOKEN,
        repository=repository,
        subject_software=subject_software,
        register_token=jm.register_token,
        allocator_url=jm.allocator_url,
        connectivity=jm.connectivity,
        client_image=jm.client_image,
        startup_script_b64=startup_b64,
        startup_on_error=main.cfg.startup_script.on_error,
        startup_max_attempts=main.cfg.startup_script.max_attempts,
        startup_base_delay_seconds=main.cfg.startup_script.base_delay_seconds,
        startup_success_check_b64=(
            base64.b64encode(
                main.cfg.startup_script.success_check.encode()
            ).decode()
            if main.cfg.startup_script.success_check
            else ""
        ),
        monitoring=monitoring,
    )

    if tunnel_prefix is not None:
        # Base address only. The client passes the prefix via -P; the
        # tunnel tool ignores any path in the URL it dials (measured), so
        # embedding the prefix here would silently produce the wrong
        # request path.
        response["tunnel_url"] = allocator_url.rstrip("/")
        response["tunnel_path_prefix"] = tunnel_prefix
        response["tunnel_bind_addr"] = f"127.0.0.{tunnel_alias_octet}"

    return jsonify(response), 200


@bp.route("/api/v1/clients/<client_id>/status", methods=["GET"])
def client_status(client_id):
    from lablink_allocator_service import main

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Invalid client secret."}), 401
    token = auth_header[7:]
    stored = main.database.get_client_secret_hash(client_id)
    if not stored or not verify_secret_cached(client_id, token, stored):
        return jsonify({"error": "Invalid client secret."}), 401

    status = main.database.get_status_by_hostname(client_id)
    return jsonify(client_id=client_id, status=status), 200


@bp.route("/api/v1/clients/<client_id>", methods=["DELETE"])
def unregister_client(client_id):
    """Best-effort caller-driven deregistration.

    Auth: Bearer client_secret (the secret minted at register time).
    Hard-deletes the row, even when ``useremail`` is set — the BYO
    operator is voluntarily withdrawing the box, and the student's
    session is already broken because the local container is going
    away.
    """
    from lablink_allocator_service import main

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Invalid client secret."}), 401
    token = auth_header[7:]
    stored = main.database.get_client_secret_hash(client_id)
    if not stored or not verify_secret_cached(client_id, token, stored):
        return jsonify({"error": "Invalid client secret."}), 401

    deleted = main.database.unregister_client(client_id)
    if not deleted:
        return jsonify({"error": "Client not found."}), 404

    # Give the connectivity strategy a chance to drop any identity it
    # minted for this client (e.g. reverse_tunnel's restrictions-file
    # rule) -- optional because most strategies need no such cleanup, so
    # it isn't part of the ClientConnectivity protocol.
    prov = current_app.config.get("LABLINK_PROVIDER") or get_provider(
        main.cfg.get("provider", None),
        region=main.cfg.app.region,
        terraform_dir=str(main.TERRAFORM_DIR),
        connectivity=main.cfg.manual.connectivity,
    )
    cleanup = getattr(prov.client_connectivity, "cleanup_client_identity", None)
    if cleanup is not None:
        cleanup(hostname=client_id)

    return jsonify(client_id=client_id, status="unregistered"), 200


@bp.route("/api/v1/clients", methods=["GET"])
@auth.login_required
def list_clients():
    """List registered clients for operator status views.

    Auth: admin HTTP Basic — same gate as ``/admin/instances``.
    Returns only operator-safe columns (no secrets, no log blobs).
    """
    from lablink_allocator_service import main

    rows = main.database.list_registered_clients()
    clients = []
    for row in rows:
        last_seen = row.get("last_seen_at")
        if isinstance(last_seen, datetime):
            last_seen = last_seen.isoformat()
        clients.append({
            "hostname": row.get("hostname"),
            "provider": row.get("provider"),
            "endpoint_url": row.get("endpoint_url"),
            "inuse": row.get("inuse"),
            "status": row.get("status"),
            "healthy": row.get("healthy"),
            "gpu_present": row.get("gpu_present"),
            "gpu_model": row.get("gpu_model"),
            "last_seen_at": last_seen,
        })
    return jsonify(clients=clients), 200


@bp.route("/api/overlay-hostname", methods=["POST"])
@require_client_secret
def report_overlay_hostname():
    """Record the overlay hostname Tailscale actually assigned this client.

    The name captured at registration is only what the client *asked* for.
    ``tailscale up --hostname=X`` exits 0 even when an existing (possibly
    offline) node already holds X, in which case Tailscale appends a numeric
    suffix instead. The allocator dials the recorded name, so an
    unreconciled rename sends every call to a dead node and the client is
    marked Unhealthy forever (lablink#404).

    Deliberately its own endpoint rather than a field on ``/api/vm-status``:
    that handler and the client's ``send_status`` are shared with the AWS
    path, where a lost status POST is unrecoverable (see start.sh's own
    comment and assign_vm's status='running' requirement). Nothing here runs
    for an AWS or lan_direct client — start.sh only calls it inside its
    ``TAILSCALE_AUTHKEY`` gate.

    Lives in this module rather than vm_telemetry because this is where the
    ``overlay_hostname`` contract is already enforced (see register_client's
    expects_overlay check). Flat ``/api/`` prefix to match the sibling
    client-VM writes (``/api/vm-status``, ``/api/gpu_health``,
    ``/api/heartbeat``) and to stay out of ``/api/v1/clients/<client_id>``'s
    path space.
    """
    from lablink_allocator_service import main

    body = request.get_json(silent=True) or {}
    hostname = body.get("hostname")
    overlay_hostname = body.get("overlay_hostname")
    if not hostname or not overlay_hostname:
        return jsonify({
            "error": "hostname and overlay_hostname required."
        }), 400

    try:
        updated = main.database.set_overlay_hostname(
            hostname=hostname, overlay_hostname=overlay_hostname
        )
    except Exception:
        current_app.logger.exception(
            "Failed to record overlay hostname for '%s'", hostname
        )
        return jsonify({"error": "Failed to record overlay hostname."}), 500

    if not updated:
        return jsonify({"error": "Not a mesh-overlay client."}), 404

    current_app.logger.info(
        "Client '%s' reported overlay hostname '%s'",
        hostname, overlay_hostname,
    )
    return jsonify({"ok": True}), 200
