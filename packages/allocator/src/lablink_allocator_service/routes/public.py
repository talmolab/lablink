"""Participant-facing routes: the landing page and seat assignment.

``/api/request_vm`` is the only unauthenticated state-changing endpoint in
the allocator — it claims a seat by email. Rejoin is idempotent: an email
that already owns a running seat keeps it rather than consuming a second.
"""
import logging
import secrets

from flask import Blueprint, current_app, jsonify, render_template, request

from lablink_allocator_service.client_session import RotationFailed
from lablink_allocator_service.providers.registry import get_provider
from lablink_allocator_service.routes.session_cookie import (
    sign_session_cookie_and_redirect,
)

bp = Blueprint("public", __name__)
logger = logging.getLogger(__name__)


@bp.route("/")
def home():
    return render_template("index.html")


@bp.route("/api/request_vm", methods=["POST"])
def submit_vm_details():
    from lablink_allocator_service import main

    import uuid

    try:
        email = (request.form.get("email") or "").strip().lower()
        if not email:
            return render_template("index.html", error="Email is required.")

        # Idempotent rejoin: if this email already owns a running seat,
        # keep them on it and continue to prep a fresh browser session.
        existing = main.database.get_assigned_vm_for_email(email=email)
        if existing is not None and existing["status"] == "running":
            hostname = existing["hostname"]
        else:
            # Fresh assignment. assign_vm atomically claims a seat and
            # returns its hostname, or raises ValueError if the pool is
            # empty; we treat that as 503 (no seats). Because the claim is
            # atomic (FOR UPDATE SKIP LOCKED), there's no separate lookup
            # to race against.
            try:
                hostname = main.database.assign_vm(email=email)
            except ValueError:
                logger.warning("Pool empty when '%s' asked for a seat", email)
                return render_template("no_seats.html"), 503

        # Mint per-session identifiers and rotate the VNC password on the
        # assigned client. RotationFailed → mark unhealthy and ask the
        # student to retry; the failed-VM recovery loop will pick it up.
        session_id = uuid.uuid4()
        browser_token = secrets.token_urlsafe(16)
        try:
            provider = current_app.config.get("LABLINK_PROVIDER") or get_provider(
                main.cfg.provider,
                region=main.cfg.app.region,
                terraform_dir=str(main.TERRAFORM_DIR),
                connectivity=main.cfg.manual.connectivity,
            )
            provider.client_connectivity.prepare_browser_session(
                database=main.database,
                hostname=hostname,
                session_id=session_id,
                browser_token=browser_token,
                agent_token=main.AGENT_TOKEN,
            )
        except RotationFailed as exc:
            logger.warning(
                "Password rotation failed for '%s' on '%s': %s",
                email, hostname, exc,
            )
            # Release the seat so the student isn't permanently wedged
            # on the rotation_failed page: without this, the rejoin
            # branch at the top of this handler keeps matching the
            # same row (status is still 'running') and re-enters
            # prepare_browser_session, which keeps failing.
            try:
                main.database.update_health(hostname=hostname, healthy="Unhealthy")
                main.database.release_seat(hostname=hostname)
            except Exception:
                logger.exception("Could not mark '%s' unhealthy", hostname)
            return render_template("rotation_failed.html"), 503

        return sign_session_cookie_and_redirect(session_id)

    except Exception as e:
        logger.error("Error in submit_vm_details: %s", e, exc_info=True)
        return render_template(
            "index.html",
            error="An unexpected error occurred while processing your request. "
            "Please ask your instructor for help.",
        )


@bp.route("/api/unassigned_vms_count", methods=["GET"])
def get_unassigned_instance_counts():
    """Get the counts of all instance types."""
    from lablink_allocator_service import main

    instance_counts = len(main.database.get_unassigned_vms())
    return jsonify(count=instance_counts), 200
