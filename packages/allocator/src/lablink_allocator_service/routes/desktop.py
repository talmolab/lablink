"""GET /desktop — cookie-gated noVNC viewer page.

Reads the signed lablink_session cookie minted by /api/request_vm,
looks up the assigned VM by session_id, and renders the noVNC viewer
configured with a WebSocket URL pointing at /proxy/<browser_token>.

If the cookie is missing, invalid, or the bound VM is no longer
running, redirect to / so the student can submit their email again.
"""
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
                    "SELECT browsertoken FROM {table} "
                    "WHERE sessionid = %s AND status = 'running'"
                ).format(table=table),
                (session_id,),
            )
            row = cur.fetchone()
    finally:
        pool.putconn(conn)

    if row is None or row[0] is None:
        return redirect("/", code=302)

    # Redirect into KasmVNC's bundled noVNC viewer (served via nginx at
    # /static/novnc/ from /usr/share/kasmvnc/www/). Kasm's noVNC is the
    # only viewer that's protocol-compatible with kasmvncserver — the
    # Debian `novnc` package sends RFB extension messages KasmVNC rejects.
    # autoconnect=1 + resize=remote tells the viewer to open the WS
    # immediately on load and follow window resizes; `path` is relative
    # to location.host, so the viewer connects to /proxy/<token> at the
    # current origin, which nginx then upgrades and proxies to KasmVNC
    # with the Basic Auth header attached server-side.
    browser_token = row[0]
    return redirect(
        f"/static/novnc/vnc.html?path=proxy/{browser_token}"
        f"&autoconnect=1&resize=remote",
        code=302,
    )
