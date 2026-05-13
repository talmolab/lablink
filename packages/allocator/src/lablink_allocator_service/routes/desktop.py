"""GET /desktop — cookie-gated noVNC viewer page.

Reads the signed lablink_session cookie minted by /api/request_vm,
looks up the assigned VM by session_id, and renders the noVNC viewer
configured with a WebSocket URL pointing at /proxy/<browser_token>.

If the cookie is missing, invalid, or the bound VM is no longer
running, redirect to / so the student can submit their email again.
"""
from flask import Blueprint, current_app, redirect, render_template, request
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

    # Pass just the token; the template derives the full ws://host/proxy/<token>
    # URL on the client so the WS scheme always matches the page's scheme.
    # Building the URL server-side from X-Forwarded-Proto is fragile across
    # front-door configurations (ALB/Caddy/CloudFlare), and getting the
    # scheme wrong gives a silent mixed-content block in the browser.
    return render_template("desktop.html", browser_token=row[0])
