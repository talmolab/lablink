"""Admin VNC troubleshooting sessions.

Three distinct affordances, deliberately separate:

* **peek** — read-only second viewer onto a participant's live session.
  Never touches useremail and never rotates credentials.
* **connect** — full control over a VM nobody is assigned to. Reserves the
  VM out of the assignable pool (AdminReservedAt) and mints a real session,
  but never sets useremail.
* **release** — ends a connect session and returns the VM to the pool.
"""
import logging
import secrets

from flask import Blueprint, current_app, redirect

from lablink_allocator_service.auth import auth
from lablink_allocator_service.client_session import RotationFailed
from lablink_allocator_service.providers.registry import get_provider
from lablink_allocator_service.routes.session_cookie import (
    sign_session_cookie_and_redirect,
)

bp = Blueprint("admin_sessions", __name__)
logger = logging.getLogger(__name__)


@bp.route("/admin/instances/<hostname>/peek")
@auth.login_required
def admin_peek_vm(hostname):
    """View (read-only) a VM already assigned to a participant, without
    touching useremail or rotating credentials — opens a second WS
    viewer onto the same live KasmVNC session."""
    from lablink_allocator_service import main

    session = main.database.get_session_for_peek(hostname)
    if session is None:
        return redirect("/admin/instances?vnc_error=peek_unavailable")

    return sign_session_cookie_and_redirect(
        session["sessionid"], suffix="view_only"
    )


@bp.route("/admin/instances/<hostname>/connect", methods=["POST"])
@auth.login_required
def admin_connect_vm(hostname):
    """Connect (full control) to a VM not currently assigned to anyone,
    for admin troubleshooting. Reserves the VM out of the assignable
    pool (AdminReservedAt) and mints a real session via the same
    prepare_browser_session path /api/request_vm uses — but never sets
    useremail."""
    from lablink_allocator_service import main

    import uuid

    if not main.database.admin_reserve_vm(hostname):
        return redirect("/admin/instances?vnc_error=connect_raced")

    try:
        session_id = uuid.uuid4()
        browser_token = secrets.token_urlsafe(16)
        provider = current_app.config.get("LABLINK_PROVIDER") or get_provider(
            main.cfg.provider,
            region=main.cfg.app.region,
            terraform_dir=str(main.TERRAFORM_DIR),
            connectivity=main.cfg.manual.connectivity,
        )
        try:
            provider.client_connectivity.prepare_browser_session(
                database=main.database,
                hostname=hostname,
                session_id=session_id,
                browser_token=browser_token,
                agent_token=main.AGENT_TOKEN,
            )
        except RotationFailed as exc:
            logger.warning(
                "Admin connect rotation failed for '%s': %s", hostname, exc
            )
            try:
                main.database.update_health(hostname=hostname, healthy="Unhealthy")
                main.database.release_seat(hostname=hostname)
            except Exception:
                logger.exception("Could not mark '%s' unhealthy", hostname)
            return redirect("/admin/instances?vnc_error=rotation_failed")

        return sign_session_cookie_and_redirect(
            session_id, suffix="admin_session"
        )
    except Exception:
        # Anything unexpected here (provider lookup, cookie signing, etc.)
        # would otherwise leave AdminReservedAt set with no page ever
        # telling the admin to release it. Release now rather than rely
        # solely on the dashboard row / 30-minute sweep to recover it.
        logger.exception(
            "Unexpected error setting up admin connect session for '%s'; "
            "releasing reservation", hostname,
        )
        try:
            main.database.release_seat(hostname=hostname)
        except Exception:
            logger.exception("Could not release seat for '%s'", hostname)
        return redirect("/admin/instances?vnc_error=connect_failed")


@bp.route("/admin/instances/<hostname>/release", methods=["POST"])
@auth.login_required
def admin_release_vm(hostname):
    """End an admin troubleshooting session, returning the VM to the
    assignable pool. Posted to by both the dashboard row's Release
    button and the /desktop wrapper page's Release form."""
    from lablink_allocator_service import main

    main.database.release_seat(hostname=hostname)
    return redirect("/admin/instances")
