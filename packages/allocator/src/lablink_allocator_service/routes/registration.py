"""POST /api/v1/clients/register and GET /api/v1/clients/<id>/status.

Lazy-imports `main` inside views to avoid the module-load import cycle
(main imports this blueprint at startup). Mirrors the rationale behind
routes/desktop.py using current_app instead of importing main.
"""
from __future__ import annotations

import psycopg2
import secrets

from flask import Blueprint, current_app, jsonify, request

from lablink_allocator_service.secret_hash import hash_secret, verify_secret

bp = Blueprint("registration", __name__)


@bp.route("/api/v1/clients/register", methods=["POST"])
def register_client():
    from lablink_allocator_service import main

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "registration rejected"}), 401
    token = auth_header[7:]

    stored = main.database.get_setting("register_token_hash")
    if not stored or not verify_secret(token, stored):
        return jsonify({"error": "registration rejected"}), 401

    body = request.get_json(silent=True) or {}
    hostname = body.get("hostname")
    machine_identity = body.get("machine_identity")
    if not hostname or not machine_identity:
        return jsonify({"error": "hostname and machine_identity required."}), 400

    provider = body.get("provider", "aws")
    client_secret = secrets.token_urlsafe(32)

    try:
        client_id = main.database.register_client(
            hostname=hostname,
            machine_identity=machine_identity,
            provider=provider,
            endpoint_url=body.get("endpoint_url"),
            provider_metadata=body.get("provider_metadata") or {},
            gpu_present=body.get("gpu_present"),
            gpu_model=body.get("gpu_model"),
            client_secret_hash=hash_secret(client_secret),
        )
    except psycopg2.IntegrityError:
        return jsonify({"error": "registration conflict"}), 409
    if client_id is None:
        return jsonify({"error": "registration conflict"}), 409

    prov = current_app.config.get("LABLINK_PROVIDER") or main.get_provider(
        main.cfg.get("provider", None),
        region=main.cfg.app.region,
        terraform_dir=str(main.TERRAFORM_DIR),
    )
    allocator_url = request.host_url.rstrip("/")
    client_image = (
        f"{main.cfg.machine.repository}:{main.cfg.machine.image}"
        if main.cfg.machine.get("repository", None)
        else main.cfg.machine.image
    )
    jm = prov.client_connectivity.make_join_material(
        allocator_url=allocator_url,
        client_image=client_image,
        register_token=token,
        hostname_hint=hostname,
    )

    return jsonify(
        client_id=client_id,
        client_secret=client_secret,
        agent_token=main.AGENT_TOKEN,
        register_token=jm.register_token,
        allocator_url=jm.allocator_url,
        connectivity=jm.connectivity,
        client_image=jm.client_image,
    ), 200


@bp.route("/api/v1/clients/<client_id>/status", methods=["GET"])
def client_status(client_id):
    from lablink_allocator_service import main

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return jsonify({"error": "Invalid client secret."}), 401
    token = auth_header[7:]
    stored = main.database.get_client_secret_hash(client_id)
    if not stored or not verify_secret(token, stored):
        return jsonify({"error": "Invalid client secret."}), 401

    status = main.database.get_status_by_hostname(client_id)
    return jsonify(client_id=client_id, status=status), 200
