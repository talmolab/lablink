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
    """Landing page.

    Renders `index.html`, the email form a participant submits to claim a
    seat.
    """
    return render_template("index.html")


@bp.route("/api/request_vm", methods=["POST"])
def submit_vm_details():
    """Claim a seat for a participant and redirect them to their desktop.

    Auth: None — this is the only unauthenticated state-changing endpoint in the allocator.

    **Request Body:** `application/x-www-form-urlencoded`

    - `email` (string, required): The participant's email address.

    **What it does:**

    1. **Idempotent rejoin.** If this email already owns a running seat, it
       keeps that seat rather than consuming a second one.
    2. **Atomic claim.** Otherwise `assign_vm` claims a free seat with
       `SELECT … FOR UPDATE SKIP LOCKED`, so concurrent requesters cannot
       collide on one VM. An empty pool raises and returns `503` with
       `no_seats.html`.
    3. **Per-session prep.** Mints a `session_id` and `browser_token`, then
       rotates the KasmVNC password on the assigned client through that
       client's local agent. The claim has already committed by this point,
       so a rotation failure is compensated for, not rolled back: the seat is
       released and the VM flagged `Unhealthy`.
    4. **Cookie + redirect.** Signs a `lablink_session` cookie bound to the
       `session_id` and redirects to `GET /desktop`.

    **Success Response:**

    - **Code:** `303 See Other` → `/desktop`, with the `lablink_session`
      cookie set.

    **Error Response:**

    - **Code:** `503 Service Unavailable` — `no_seats.html` when the pool is
      empty, or `rotation_failed.html` when the assigned client could not be
      reached. On a rotation failure the seat is released and the VM flagged
      `Unhealthy` so the participant isn't wedged on a dead machine.
    - **Code:** `200 OK` — `index.html` re-rendered with an error if `email`
      is missing.

    The participant supplies nothing but an email address.
    """
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
                tofu_dir=str(main.TOFU_DIR),
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

        # Rotation succeeded, so the client is reachable — clear any
        # Unhealthy flag a previous transient failure left behind. Reachable
        # here via the rejoin branch above, which matches on status='running'
        # rather than going through assign_vm and so can land on a row still
        # marked Unhealthy (lablink#404).
        try:
            main.database.clear_unhealthy(hostname=hostname)
        except Exception:
            logger.exception(
                "Could not clear unhealthy flag for '%s'", hostname
            )

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
    """Get the number of available (unassigned) VMs.

    Returns the current count of VMs that are running and not yet assigned
    to a user.

    Auth: None (health/monitoring).

    **Success Response:**

    - **Code:** `200 OK`
    - **Content:**
      ```json
      {
        "count": 5
      }
      ```

    **Client Usage:** Not used by the client service. Intended for external
    monitoring or UI components on the allocator to display the number of
    available VMs.
    """
    from lablink_allocator_service import main

    instance_counts = len(main.database.get_unassigned_vms())
    return jsonify(count=instance_counts), 200
