"""POST /internal/proxy_auth — nginx auth_request callback.

Validates the lablink_session cookie and the browser_token from the
original URI; on success, returns X-Upstream and X-Auth-Basic response
headers so nginx can dial the upstream KasmVNC and attach the HTTP
Basic Authorization header to the upstream WebSocket handshake.
KasmVNC's auth is username-based; we use a fixed username and rotate
only the password. The browser never sees either.
"""
import base64
import re

from flask import Blueprint, current_app, make_response, request
from psycopg2 import sql

from ..signed_cookie import (
    InvalidSignature,
    get_or_create_cookie_secret,
    verify,
)


bp = Blueprint("internal_proxy_auth", __name__)
_TOKEN_RE = re.compile(r"^/proxy/([A-Za-z0-9_-]+)$")
KASMVNC_USERNAME = "kasm_user"


def _unauth():
    return make_response(("", 401))


@bp.route("/internal/proxy_auth", methods=["GET", "POST"])
def proxy_auth():
    """nginx `auth_request` gate for the desktop WebSocket proxy.

    Auth: None — an `auth_request` subrequest target for the allocator's own nginx, never routed publicly.

    nginx calls this before proxying desktop bytes, to check that the
    requesting session is entitled to the client it is asking for: the
    signed `lablink_session` cookie must resolve to the VM whose
    `browser_token` appears in the original URI.
    """
    raw_cookie = request.cookies.get("lablink_session")
    original_uri = request.headers.get("X-Original-URI", "")
    if not raw_cookie:
        return _unauth()
    m = _TOKEN_RE.match(original_uri)
    if not m:
        return _unauth()
    token = m.group(1)

    pool = current_app.config["DB_POOL"]
    conn = pool.getconn()
    try:
        secret = get_or_create_cookie_secret(conn)
        try:
            payload = verify(raw_cookie, secret=secret)
        except InvalidSignature:
            return _unauth()
        session_id = payload.partition(":")[0]
        table = sql.Identifier(current_app.config["VM_TABLE_NAME"])
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT upstream, vncpassword FROM {table} "
                    "WHERE sessionid = %s AND browsertoken = %s "
                    "      AND status = 'running'"
                ).format(table=table),
                (session_id, token),
            )
            row = cur.fetchone()
    finally:
        pool.putconn(conn)

    if row is None:
        return _unauth()
    upstream, vnc_password = row
    if upstream is None or vnc_password is None:
        return _unauth()
    encoded = base64.b64encode(
        f"{KASMVNC_USERNAME}:{vnc_password}".encode()
    ).decode()
    resp = make_response(("", 200))
    resp.headers["X-Upstream"] = upstream
    resp.headers["X-Auth-Basic"] = f"Basic {encoded}"
    return resp


@bp.route("/internal/tunnel_auth", methods=["GET", "POST"])
def tunnel_auth():
    """nginx auth_request gate for the reverse-tunnel WebSocket upgrade.

    The path prefix identifies which client is attaching; the bearer token
    is what authenticates it. Both must agree, so a client cannot attach
    under another client's prefix even holding a valid secret of its own.

    This check is the ONLY binding between a secret and an identity.
    tunnel_manager's restrictions are keyed by path prefix, so they grant
    whatever alias the presented path claims -- they constrain a client to
    one alias, they do not prove who the client is. Do not describe them as
    a second authentication layer.
    """
    from lablink_allocator_service import main
    from lablink_allocator_service.secret_hash import verify_secret_cached

    # nginx captured the prefix from the FIRST path segment and passed it
    # here; do not re-derive it from the URI. The client's request path is
    # /<prefix>/events, so last-segment extraction yields "events" and 401s
    # every legitimate attach (measured against the real client).
    prefix = (request.headers.get("X-Tunnel-Prefix") or "").strip()
    auth = request.headers.get("X-Tunnel-Auth") or ""
    if not prefix or not auth.startswith("Bearer "):
        return _unauth()
    token = auth[len("Bearer "):].strip()
    if not token:
        return _unauth()

    found = main.database.get_tunnel_path_prefix(prefix)
    if not found:
        return _unauth()
    client_id, _ = found
    stored = main.database.get_client_secret_hash(client_id)
    if not stored or not verify_secret_cached(client_id, token, stored):
        return _unauth()
    return make_response(("", 200))
