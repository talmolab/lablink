"""Authentication for the allocator service.

Two independent gates:

* ``auth`` — HTTP Basic, admin operator credentials, guards ``/admin/*`` and
  the operator JSON APIs.
* ``require_client_secret`` — Bearer token, per-client secret minted at
  registration, guards the client-VM → allocator telemetry endpoints.

This module exists separately from ``main`` so blueprints can apply
``@auth.login_required`` as a normal decorator at import time. ``main``
creates the Flask app and imports the blueprints, so an ``auth`` defined in
``main`` does not exist yet when a blueprint module body executes.

``users`` and ``database`` stay on ``main`` and are read through a lazy import
at request time — the test suite patches ``main.users`` and ``main.database``,
and a module-level binding here would freeze pre-patch values.
"""

from functools import wraps

from flask import jsonify, request
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import check_password_hash

from lablink_allocator_service.secret_hash import verify_secret_cached

auth = HTTPBasicAuth()


@auth.verify_password
def verify_password(username, password):
    """Verify the username and password against the stored users.
    Args:
        username (str): The username to verify.
        password (str): The password to verify.
    Returns:
        str: The username if the credentials are valid, None otherwise.
    """
    from lablink_allocator_service import main

    if username in main.users and check_password_hash(
        main.users.get(username), password
    ):
        return username


def require_client_secret(f):
    """Require a valid per-client secret Bearer token. The client row is
    resolved from the request's hostname field (`vm_id` for heartbeat,
    else `hostname`; falls back to a `hostname` route kwarg)."""

    @wraps(f)
    def decorated(*args, **kwargs):
        from lablink_allocator_service import main

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

        stored = main.database.get_client_secret_hash(hostname)
        if not stored or not verify_secret_cached(hostname, token, stored):
            return jsonify({"error": "Invalid client secret."}), 401
        return f(*args, **kwargs)

    return decorated
