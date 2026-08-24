"""The allocator's own logs: a JSON tail plus the admin page that shows it.

Its own blueprint rather than part of admin_pages because this is the one
log source that comes off the local filesystem instead of the database --
start.sh writes it, since nothing mounts docker.sock and the allocator
therefore cannot run `docker logs` on itself.
"""
import logging

from flask import Blueprint, jsonify, render_template, request

from lablink_allocator_service.auth import auth
from lablink_allocator_service.utils.log_filter import filter_errors
from lablink_allocator_service.utils.log_tail import read_allocator_log

bp = Blueprint("allocator_logs", __name__)

logger = logging.getLogger(__name__)

_MISSING_LOG_MSG = (
    "No log file under /var/log/lablink -- start.sh writes it, so it is "
    "absent outside the container. Run `lablink logs` instead."
)


@bp.route("/api/allocator-logs", methods=["GET"])
@auth.login_required
def allocator_logs_api():
    """Get the allocator's own logs.

    Returns a redacted tail (last 2000 lines) of the allocator's own
    container output, read from the file `start.sh` writes at
    `/var/log/lablink/allocator.log`. Backs the `/admin/allocator-logs`
    page. Values of `PASSWORD`/`TOKEN`/`SECRET`/`KEY` assignments are masked
    before the response leaves the process.

    **Query Parameters:**

    - `errors_only` (boolean, optional, default `false`): As on
      `GET /api/vm-logs/<hostname>` — reduces `docker_logs` to its error
      lines. `error` still reports only a genuinely missing log file; a log
      with no error lines returns `docker_logs: ""` with `error: null`.

    **Success Response:**

    - **Code:** `200 OK`
    - **Content:**
      ```json
      {
        "cloud_init_logs": null,
        "docker_logs": "2026-08-03 12:00:00 - Starting nginx on :5000...",
        "error": null
      }
      ```

    The response mirrors `/api/vm-logs/<hostname>`'s keys so the shared logs
    template's JavaScript works unchanged. `cloud_init_logs` is always
    `null`: the allocator host's cloud-init output lives outside the
    container and is out of scope. When no log file exists, `docker_logs` is
    `null` and `error` explains why — the response is still `200`.
    """
    logs = read_allocator_log()
    # Capture missing-ness *before* filtering: a log with no error lines
    # filters down to "", which is falsy, and would otherwise be reported
    # as a missing log file.
    missing = logs is None
    if request.args.get("errors_only", "false").lower() == "true":
        logs = filter_errors(logs)
    return jsonify(
        {
            "cloud_init_logs": None,
            "docker_logs": logs,
            "error": _MISSING_LOG_MSG if missing else None,
        }
    )


@bp.route("/admin/allocator-logs", methods=["GET"])
@auth.login_required
def allocator_logs_page():
    """Render the shared logs page pointed at this blueprint's API."""
    return render_template(
        "instance-logs.html",
        log_title="Allocator Logs",
        log_endpoint="/api/allocator-logs",
        download_slug="allocator",
        show_cloud_init=False,
        # Reached via same-tab navigation from /admin, so window.close() is a no-op.
        show_close=False,
    )
