"""Signing and setting the ``lablink_session`` cookie.

Shared by ``/api/request_vm`` (student) and the admin peek/connect routes so
the cookie-hardening flags (httponly, samesite, secure) cannot drift apart
across call sites.
"""

from flask import Response, redirect, request

from lablink_allocator_service.signed_cookie import (
    get_or_create_cookie_secret,
    sign,
)


def sign_session_cookie_and_redirect(
    session_id, *, suffix: str = ""
) -> Response:
    """Sign ``session_id`` (optionally with a ``:suffix``) into the
    lablink_session cookie and redirect to /desktop.

    Args:
        session_id: The session identifier to sign (str or UUID).
        suffix: Optional payload suffix (e.g. "view_only", "admin_session").
            Omitted entirely for a bare student session.
    """
    from lablink_allocator_service import main

    conn = main.database._pool.getconn()
    try:
        secret = get_or_create_cookie_secret(conn)
    finally:
        main.database._pool.putconn(conn)

    payload = f"{session_id}:{suffix}" if suffix else str(session_id)
    signed = sign(payload, secret=secret)
    resp = redirect("/desktop", code=303)
    # Secure flag is decided by whether the inbound request was https —
    # front door (ALB/Caddy/Cloudflare) sets X-Forwarded-Proto.
    is_https = request.headers.get("X-Forwarded-Proto") == "https"
    resp.set_cookie(
        "lablink_session", signed,
        httponly=True, samesite="Strict",
        secure=is_https, path="/",
    )
    return resp
