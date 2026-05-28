"""GET /desktop — cookie-gated noVNC viewer page.

Reads the signed lablink_session cookie minted by /api/request_vm,
looks up the assigned VM by session_id, and renders the noVNC viewer
configured from the persisted browser_ws_url and browser_credential.

If the cookie is missing, invalid, or the bound VM is no longer
running, redirect to / so the student can submit their email again.
"""
import json
from urllib.parse import quote, urlsplit

from flask import Blueprint, current_app, redirect, request
from psycopg2 import sql

from ..signed_cookie import (
    InvalidSignature,
    get_or_create_cookie_secret,
    verify,
)


bp = Blueprint("desktop", __name__)


@bp.route("/desktop")
def desktop():
    raw_cookie = request.cookies.get("lablink_session")
    if not raw_cookie:
        return redirect("/", code=302)

    pool = current_app.config["DB_POOL"]
    conn = pool.getconn()
    try:
        secret = get_or_create_cookie_secret(conn)
        try:
            session_id = verify(raw_cookie, secret=secret)
        except InvalidSignature:
            return redirect("/", code=302)

        table = sql.Identifier(current_app.config["VM_TABLE_NAME"])
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT browser_ws_url, browser_credential FROM {table} "
                    "WHERE sessionid = %s AND status = 'running'"
                ).format(table=table),
                (session_id,),
            )
            row = cur.fetchone()
    finally:
        pool.putconn(conn)

    if row is None or row[0] is None:
        return redirect("/", code=302)

    ws_url, credential = row[0], row[1]

    # Proxied path (relative, server-side credential): byte-identical to
    # the historical viewer URL — AWS regression-locked.
    if ws_url.startswith("proxy/"):
        return redirect(
            f"/static/novnc/vnc.html?path={ws_url}"
            f"&autoconnect=1&resize=remote",
            code=302,
        )

    # Direct ws(s):// target (manual / lan_direct connectivity):
    # the browser opens the WS straight at the client KasmVNC, with no
    # allocator proxy in the byte path. Modern Chromium/Firefox refuse
    # to attach an `Authorization: Basic` header to a WebSocket upgrade
    # (URL userinfo is stripped at the URL-parser level), so we drive
    # KasmVNC in RFB `VncAuth` mode on this connectivity and pass the
    # per-session 8-char credential through the bundled noVNC's
    # `?password=` URL param — it consumes it in-band during the VNC
    # auth handshake. The credential sits in the WS-viewer URL, but
    # `/static/novnc/*` has `access_log off` in lablink-nginx.conf and
    # we use `location.replace` to keep the URL out of session history.
    # DevTools visibility is unavoidable for any browser-direct auth
    # scheme; per-session rotation bounds the exposure window.
    parts = urlsplit(ws_url)
    host = parts.hostname or ""
    port = parts.port or 6080
    encrypt = "1" if parts.scheme == "wss" else "0"
    pw_qs = "" if credential is None else f"&password={quote(credential, safe='')}"
    target = (
        f"/static/novnc/vnc.html?host={host}&port={port}&encrypt={encrypt}"
        f"&autoconnect=1&resize=remote{pw_qs}"
    )
    return (
        "<!doctype html><meta charset=utf-8>"
        '<body style="margin:0">'
        f"<script>location.replace({json.dumps(target)});</script>",
        200,
    )
