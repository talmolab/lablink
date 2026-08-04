"""The allocator's own logs: a JSON tail plus the admin page that shows it.

Its own blueprint rather than part of admin_pages because this is the one
log source that comes off the local filesystem instead of the database --
start.sh writes it, since nothing mounts docker.sock and the allocator
therefore cannot run `docker logs` on itself.
"""
import logging

from flask import Blueprint, jsonify, render_template

from lablink_allocator_service.auth import auth
from lablink_allocator_service.utils.log_tail import read_allocator_log

bp = Blueprint("allocator_logs", __name__)

logger = logging.getLogger(__name__)

_MISSING_LOG_MSG = (
    "No allocator log file found under /var/log/lablink. This page reads "
    "the file start.sh writes inside the container, so it is empty when "
    "the allocator runs outside its container or from an image predating "
    "this feature. Run `lablink logs` instead."
)


@bp.route("/api/allocator-logs", methods=["GET"])
@auth.login_required
def allocator_logs_api():
    """Return a redacted tail of the allocator's own log file.

    Mirrors /api/vm-logs/<hostname>'s response keys so the shared logs
    template's JavaScript works unchanged. cloud_init_logs is always None:
    the allocator's cloud-init output lives on the EC2 host, outside this
    container, and is deliberately out of scope.
    """
    logs = read_allocator_log()
    return jsonify(
        {
            "cloud_init_logs": None,
            "docker_logs": logs,
            "error": None if logs else _MISSING_LOG_MSG,
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
