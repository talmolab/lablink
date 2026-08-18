"""Health and capacity reporting.

`GET /api/health` reports per-dependency readiness rather than a bare 200 so
a deployment stuck mid-startup is distinguishable from a healthy one: 200 +
"healthy" only once every check passes, 503 + "starting" otherwise.

`GET /api/health/connections` reports Postgres connection usage against the
configured maximum. Deliberately a *separate* route: /api/health is polled in
a tight loop by start.sh during boot and by `lablink deploy` afterwards, and
neither should pay for a Postgres aggregate to learn whether the service is up.
"""
import logging
import subprocess
import time

import psycopg2
from flask import Blueprint, current_app, jsonify

from lablink_allocator_service.auth import auth
from lablink_allocator_service.db.pool import PooledCursor

bp = Blueprint("health", __name__)
logger = logging.getLogger(__name__)

# Shared by _tunnel_status() (which produces it) and health_check() (which
# excludes it from the readiness gate). One constant rather than two literals
# so the two can't drift apart.
_UNATTACHED_SUFFIX = " client(s) not attached"


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


def _tunnel_status() -> str:
    """Tunnel health as a *pairing* property, not a process one.

    tunnel_manager.tunnel_status() only says the shared server is up. A
    client whose tunnel died leaves its alias bound for the idle timeout,
    and connections to that orphan hang rather than fail -- so a registered
    client with no listening alias is the condition worth reporting.

    Guards the same "not initialized" window the top-level `database`
    check already names, and catches psycopg2.Error the same way
    `_tailscale_status` catches its own external call's (OSError,
    TimeoutExpired) -- so a transient Postgres problem (pool exhaustion,
    a brief restart) degrades this one check's value instead of raising
    out of the route and 500ing the whole endpoint.
    """
    from lablink_allocator_service import main, tunnel_manager

    server = tunnel_manager.tunnel_status()
    if server != "ok":
        return server
    if main.database is None:
        return "not initialized"
    try:
        expected = set(main.database.list_tunnel_aliases())
    except psycopg2.Error:
        return "client list unavailable"
    missing = expected - tunnel_manager.attached_aliases()
    return f"{len(missing)}{_UNATTACHED_SUFFIX}" if missing else "ok"


def connection_stats() -> dict | None:
    """Postgres client connection usage, or None if unreadable.

    None rather than raising: both callers must degrade -- /admin renders
    "unavailable" and the JSON route answers 503.
    """
    from lablink_allocator_service import main

    try:
        # client backends only: pg_stat_activity rows include background workers
        # (checkpointer, walwriter, the launchers), which hold no
        # max_connections slot. Measured live: 10 rows for 5 real connections.
        # LIKE, not '=', so 'idle in transaction (aborted)' counts too -- it
        # pins locks the same way. max_connections read from Postgres because
        # start.sh sets it and a literal here would drift.
        #
        # ponytail: measured *through* the pool, so an exhausted pool returns
        # None instead of numbers. Use a dedicated connection if saturation
        # reporting has to survive saturation.
        with PooledCursor(main.database.pool) as cursor:
            cursor.execute(
                "SELECT count(*) FILTER (WHERE backend_type = 'client backend'), "
                "count(*) FILTER (WHERE state LIKE 'idle in transaction%'), "
                "current_setting('max_connections')::int "
                "FROM pg_stat_activity"
            )
            active, idle_in_transaction, max_connections = cursor.fetchone()
    except Exception:
        # Broad on purpose: rendered inside /admin, so anything escaping here
        # 500s the operator's panel. Logged with a traceback, never swallowed.
        logger.warning("Postgres connection stats unavailable", exc_info=True)
        return None

    util = active / max(max_connections, 1)
    return {
        "active_connections": active,
        "idle_in_transaction": idle_in_transaction,
        "max_connections": max_connections,
        "utilization_percent": round(util * 100, 1),
        "level": "critical" if util > 0.9 else "warning" if util > 0.8 else "ok",
    }


@bp.route("/api/health", methods=["GET"])
def health_check():
    """Readiness check.

    Auth: None — this is what load balancers, `lablink deploy` and `lablink status` poll.

    Returns a structured readiness report rather than a bare 200. The
    `checks` map always covers `database`, `scheduler` and `reboot_service`,
    and gains a `tailscale` entry when the configured connectivity needs
    one, or a `tunnel` entry for reverse-tunnel deployments.

    **Success Response:**

    - **Code:** `200 OK` when every gating check is `ok`
    - **Content:**
      ```json
      {
        "status": "healthy",
        "checks": {
          "database": "ok",
          "scheduler": "ok",
          "reboot_service": "ok"
        },
        "uptime_seconds": 123.4
      }
      ```

    **Error Response:**

    - **Code:** `503 Service Unavailable` with `"status": "starting"` when a
      gating check fails.

    A dead client tunnel does not make the allocator unready: unattached
    client tunnels are reported but deliberately don't gate readiness — a
    registering client is unattached until its tunnel comes up. The
    allocator's own dependencies (tunnel server, database) do gate.
    """
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
    connectivity = current_app.config["LABLINK_PROVIDER"].client_connectivity
    if connectivity.requires_tailscale_check:
        checks["tailscale"] = _tailscale_status()
    if getattr(connectivity, "requires_tunnel_check", False):
        checks["tunnel"] = _tunnel_status()

    # A registered client whose tunnel isn't attached is reported but does not
    # gate readiness: the allocator is serving fine, and nothing about one
    # student's dead tunnel makes it unready. Gating on it also deadlocked the
    # client's own startup — a registering client is "not attached" by
    # definition until its tunnel is up, and it won't bring that tunnel up
    # while this endpoint answers 503 (observed live 2026-07-31). The other
    # tunnel values (server down, DB error) DO gate: those are the allocator's
    # own dependencies failing.
    all_ready = all(
        v == "ok"
        for k, v in checks.items()
        if not (k == "tunnel" and v.endswith(_UNATTACHED_SUFFIX))
    )
    status = "healthy" if all_ready else "starting"
    code = 200 if all_ready else 503

    payload = {
        "status": status,
        "checks": checks,
    }

    if main._startup_time is not None:
        payload["uptime_seconds"] = round(time.monotonic() - main._startup_time, 1)

    return jsonify(payload), code


@bp.route("/api/health/connections", methods=["GET"])
@auth.login_required
def connection_health():
    """Report PostgreSQL connection usage.

    Reports usage against the server's configured maximum, for checking
    headroom before scaling a deployment up.

    `active_connections` counts client backends only — the things
    `max_connections` bounds — excluding the background-worker rows
    `pg_stat_activity` also carries. It includes the connection serving this
    request. `max_connections` is read from PostgreSQL, so it tracks
    whatever is actually configured.

    `idle_in_transaction` distinguishes a leaked pooled connection from
    ordinary load; a non-zero value that doesn't fall back to zero is worth
    investigating. It counts `idle in transaction (aborted)` too — an
    aborted-but-open transaction pins locks just like a live one.

    The same numbers appear on the `/admin` panel, which escalates to a
    banner above 90%.

    **Success Response:**

    - **Code:** `200 OK`
    - **Content:**
      ```json
      {
        "status": "ok",
        "active_connections": 61,
        "idle_in_transaction": 0,
        "max_connections": 300,
        "utilization_percent": 20.3,
        "level": "ok"
      }
      ```

    `level` is `ok`, `warning` above 80% utilization, or `critical` above
    90%. High utilization still answers `200` — busy is not broken.

    **Error Response:**

    - **Code:** `503 Service Unavailable` with `{"status": "unavailable"}`
      when the numbers can't be read — the database isn't initialized yet,
      or the query failed (including a pool with no free connections). Never
      means the pool is merely busy.
    """
    stats = connection_stats()
    if stats is None:
        return jsonify({"status": "unavailable"}), 503
    return jsonify({"status": "ok", **stats}), 200
