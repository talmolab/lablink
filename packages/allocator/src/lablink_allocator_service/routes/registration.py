"""POST /api/v1/clients/register and GET /api/v1/clients/<id>/status.

Lazy-imports `main` inside views to avoid the module-load import cycle
(main imports this blueprint at startup). Mirrors the rationale behind
routes/desktop.py using current_app instead of importing main.
"""
from __future__ import annotations

import base64
from datetime import datetime
import psycopg2
import secrets

from flask import Blueprint, current_app, jsonify, request

from lablink_allocator_service.secret_hash import (
    REGISTER_TOKEN_SUBJECT,
    hash_secret,
    verify_secret_cached,
)

bp = Blueprint("registration", __name__)


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

    provider = body.get("provider", "aws")
    provider_metadata = body.get("provider_metadata") or {}

    prov = current_app.config.get("LABLINK_PROVIDER") or main.get_provider(
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

    client_secret = secrets.token_urlsafe(32)

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

    allocator_url = request.host_url.rstrip("/")
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
        hostname_hint=hostname,
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

    return jsonify(
        client_id=client_id,
        client_secret=client_secret,
        agent_token=main.AGENT_TOKEN,
        register_token=jm.register_token,
        allocator_url=jm.allocator_url,
        connectivity=jm.connectivity,
        client_image=jm.client_image,
        startup_script_b64=startup_b64,
        startup_on_error=main.cfg.startup_script.on_error,
        monitoring=monitoring,
    ), 200


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

    return jsonify(client_id=client_id, status="unregistered"), 200


@bp.route("/api/v1/clients", methods=["GET"])
def list_clients():
    """List registered clients for operator status views.

    Auth: admin HTTP Basic — same gate as ``/admin/instances``.
    Returns only operator-safe columns (no secrets, no log blobs).
    """
    # Lazy import + manual decorator application: `main.auth` is only
    # created when main.py imports this blueprint, so we can't decorate
    # at module load time.
    from lablink_allocator_service import main

    def _handler():
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

    return main.auth.login_required(_handler)()
