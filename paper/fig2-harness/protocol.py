#!/usr/bin/env python3
"""Fixed experimental contract for Fig. 2.

The collector, runner, processor, and plotter import these values so a live
session cannot drift from the method described in the figure caption.
"""

from __future__ import annotations

ARM_SIZES = (5, 10, 30, 60)
REPLICATE_ORDERS = (
    (5, 10, 30, 60),
    (60, 30, 10, 5),
    (10, 60, 5, 30),
)

READY_TIMEOUT_S = 15 * 60
SOAK_SECONDS = 10 * 60
DEFAULT_POLL_INTERVAL_S = 5.0
MAX_CONSECUTIVE_POLL_ERRORS = 2

METRIC_DEFINITIONS = {
    "provisioning_time_s": (
        "operation finished_at minus started_at, one value per arm replicate"
    ),
    "seat_ready_time_s": (
        "first collector observation with status=running minus launch request"
    ),
    "all_ready_time_s": (
        "maximum seat-ready time across all intended VMs; undefined on failure"
    ),
    "seat_claim": "first non-null SessionStartedAt or UserEmail; never InUse",
    "retry_rate": "VMs with a reboot_count increase divided by intended N",
    "failure_rate": "intended VMs never ready by timeout divided by intended N",
    "instability_rate": (
        "intended VMs that ready then regress, become unhealthy, or disappear "
        "before teardown divided by intended N"
    ),
}


def validate_contract() -> None:
    """Raise if the fixed run matrix is internally inconsistent."""
    expected = set(ARM_SIZES)
    if len(REPLICATE_ORDERS) < 3:
        raise RuntimeError("Fig. 2 requires at least three independent replicates")
    for index, order in enumerate(REPLICATE_ORDERS, start=1):
        if len(order) != len(ARM_SIZES) or set(order) != expected:
            raise RuntimeError(
                f"replicate {index} must contain every arm size exactly once"
            )
    if READY_TIMEOUT_S <= 0 or SOAK_SECONDS <= 0 or DEFAULT_POLL_INTERVAL_S <= 0:
        raise RuntimeError("protocol durations must be positive")


validate_contract()
