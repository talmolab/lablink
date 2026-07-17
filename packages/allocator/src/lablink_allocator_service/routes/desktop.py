"""GET /desktop — cookie-gated noVNC viewer page.

Reads the signed lablink_session cookie minted by /api/request_vm,
looks up the assigned VM by session_id, and renders the noVNC viewer
configured from the persisted browser_ws_url and browser_credential.

If the cookie is missing, invalid, or the bound VM is no longer
running, redirect to / so the student can submit their email again.
"""
import html
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
            payload = verify(raw_cookie, secret=secret)
        except InvalidSignature:
            return redirect("/", code=302)
        session_id, _, suffix = payload.partition(":")

        table = sql.Identifier(current_app.config["VM_TABLE_NAME"])
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "SELECT browser_ws_url, browser_credential, hostname "
                    "FROM {table} "
                    "WHERE sessionid = %s AND status = 'running'"
                ).format(table=table),
                (session_id,),
            )
            row = cur.fetchone()
    finally:
        pool.putconn(conn)

    if row is None or row[0] is None:
        return redirect("/", code=302)

    ws_url, credential, hostname = row
    view_only = suffix == "view_only"

    if suffix == "admin_session":
        return _render_admin_session_page(ws_url, hostname)

    # Proxied path (relative, server-side credential): byte-identical to
    # the historical viewer URL — AWS regression-locked.
    if ws_url.startswith("proxy/"):
        vo_qs = "&view_only=1" if view_only else ""
        return redirect(
            f"/static/novnc/vnc.html?path={ws_url}"
            f"&autoconnect=1&resize=remote{vo_qs}",
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
    vo_qs = "&view_only=1" if view_only else ""
    target = (
        f"/static/novnc/vnc.html?host={host}&port={port}&encrypt={encrypt}"
        f"&autoconnect=1&resize=remote{pw_qs}{vo_qs}"
    )
    return (
        "<!doctype html><meta charset=utf-8>"
        '<body style="margin:0">'
        f"<script>location.replace({json.dumps(target)});</script>",
        200,
    )


def _render_admin_session_page(ws_url: str, hostname: str) -> str:
    """Wrap the noVNC viewer with a persistent Release control for an
    admin troubleshooting session (full control, no participant assigned).

    Unlike the student/peek paths (a bare redirect), this renders
    directly, since the Release form needs to know the hostname.
    """
    viewer_src = f"/static/novnc/vnc.html?path={ws_url}&autoconnect=1&resize=remote"
    release_action = f"/admin/instances/{quote(hostname, safe='')}/release"
    safe_hostname = html.escape(hostname)
    return f"""<!doctype html>
<meta charset="utf-8">
<style>
  body {{ margin: 0; display: flex; flex-direction: column; height: 100vh; }}
  header {{
    flex: 0 0 auto; background: #222; color: #fff; padding: 8px 16px;
    display: flex; align-items: center; justify-content: space-between;
    font-family: sans-serif;
  }}
  header form {{ margin: 0; }}
  header button {{
    background: #c0392b; color: #fff; border: none; padding: 6px 14px;
    border-radius: 4px; cursor: pointer;
  }}
  iframe {{ flex: 1 1 auto; border: none; }}
</style>
<header>
  <span>Admin session on {safe_hostname}</span>
  <form method="POST" action="{release_action}">
    <button type="submit">Release</button>
  </form>
</header>
<iframe src="{viewer_src}"></iframe>
"""
