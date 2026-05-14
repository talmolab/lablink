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
            session_id = verify(raw_cookie, secret=secret)
        except InvalidSignature:
            return _unauth()
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
