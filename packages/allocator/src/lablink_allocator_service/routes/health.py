"""GET /api/health — structured readiness probe.

Reports per-dependency readiness rather than a bare 200 so a deployment
stuck mid-startup is distinguishable from a healthy one: 200 + "healthy"
only once every check passes, 503 + "starting" otherwise.
"""

import subprocess
import time

from flask import Blueprint, current_app, jsonify

bp = Blueprint("health", __name__)


def _tailscale_status() -> str:
    """Return "ok" / "not joined" for the allocator's own tailnet
    connection.

    The mesh-overlay sidecar shares the allocator's *network* namespace
    (network_mode: service:allocator) but not its filesystem, so the
    `tailscale` CLI binary — which lives only in the sidecar's image —
    is never present here; shelling out to it would always report
    "not installed" regardless of whether the sidecar actually joined.

    Checking for the shared `tailscale0` interface's existence alone is
    not enough either: confirmed live against a real tailnet, the kernel
    interface stays up (`UP,LOWER_UP`, with a link-local IPv6 address)
    even while the node is logged out and unauthenticated with the
    control plane — a control-plane hiccup can leave the device node
    behind with no working overlay path. Requiring an actual Tailscale
    IPv4 address (only assigned once the control plane has authenticated
    the node) avoids that false positive, still with no CLI and no
    socket-sharing between the two containers."""
    try:
        result = subprocess.run(
            ["ip", "-4", "-o", "addr", "show", "tailscale0"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "not joined"
    return "ok" if result.returncode == 0 and "inet " in result.stdout else "not joined"


@bp.route("/api/health", methods=["GET"])
def health_check():
    """Return structured readiness status."""
    from lablink_allocator_service import main

    checks = {
        "database": "ok" if main.database is not None else "not initialized",
        "scheduler": (
            "ok" if main.scheduler_service is not None else "not initialized"
        ),
        "reboot_service": (
            "ok" if main.reboot_service is not None else "not initialized"
        ),
    }
    if current_app.config[
        "LABLINK_PROVIDER"
    ].client_connectivity.requires_tailscale_check:
        checks["tailscale"] = _tailscale_status()

    all_ready = all(v == "ok" for v in checks.values())
    status = "healthy" if all_ready else "starting"
    code = 200 if all_ready else 503

    payload = {
        "status": status,
        "checks": checks,
    }

    if main._startup_time is not None:
        payload["uptime_seconds"] = round(time.monotonic() - main._startup_time, 1)

    return jsonify(payload), code
