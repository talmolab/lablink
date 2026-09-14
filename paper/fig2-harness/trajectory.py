#!/usr/bin/env python3
"""Pure derivations over a Fig 2 trajectory CSV.

Everything panels B, C and D report comes from here. The one rule the
module exists to enforce: a conclusion is drawn from the sequence of
snapshots, never from the last one. The VM table holds terminal state
only, so the last snapshot cannot distinguish "no VM ever failed" from
"the failures were replaced and their rows are gone".
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

_FLOAT_FIELDS = (
    "poll_epoch",
    "clock_offset_s",
    "tofu_start_epoch",
    "tofu_end_epoch",
    "cloudinit_start_epoch",
    "cloudinit_end_epoch",
    "container_start_epoch",
    "container_end_epoch",
    "total_startup_s",
    "created_epoch",
    "session_started_epoch",
    "last_seen_epoch",
)
_INT_FIELDS = ("arm_n", "replicate", "reboot_count")


def load_trajectory(path: Path) -> list[dict]:
    """Read a trajectory CSV back with numbers as numbers."""
    rows: list[dict] = []
    with Path(path).open(newline="") as handle:
        for src in csv.DictReader(handle):
            row = dict(src)
            for field in _FLOAT_FIELDS:
                text = (row.get(field) or "").strip()
                row[field] = float(text) if text and text != "None" else None
            for field in _INT_FIELDS:
                text = (row.get(field) or "").strip()
                row[field] = int(float(text)) if text and text != "None" else None
            rows.append(row)
    return rows


def by_host(rows: list[dict]) -> dict[str, list[dict]]:
    """Group rows by physical identity, including pre-registration snapshots.

    A VM first appears under its configured hostname; ``machine_identity`` is
    populated a few minutes later when the client registers. Associate those
    early rows with the next identity observed for that hostname so one VM is
    not counted twice. Rows that already carry an identity always use it,
    preserving replacement detection when a hostname is reused.
    """
    identities: dict[str, list[tuple[float, str]]] = {}
    for row in rows:
        if row.get("machine_identity"):
            identities.setdefault(row["hostname"], []).append(
                (row["poll_epoch"], row["machine_identity"])
            )
    for observations in identities.values():
        observations.sort()

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        identity = row.get("machine_identity")
        if not identity:
            observations = identities.get(row["hostname"], [])
            identity = next(
                (
                    observed_identity
                    for epoch, observed_identity in observations
                    if epoch >= row["poll_epoch"]
                ),
                observations[-1][1] if observations else row["hostname"],
            )
        grouped.setdefault(identity, []).append(row)
    for host_rows in grouped.values():
        host_rows.sort(key=lambda r: r["poll_epoch"])
    return grouped


def intended_by_host(rows: list[dict], expected_n: int) -> dict[str, list[dict]]:
    """Select the first observed cohort; later identities are replacements."""
    hosts = by_host(rows)
    ordered = sorted(
        hosts.items(), key=lambda item: (item[1][0]["poll_epoch"], item[0])
    )
    return dict(ordered[:expected_n])


def readiness_epoch(host_rows: list[dict]) -> float | None:
    """Collector time when this host was first observed seat-ready."""
    for row in host_rows:
        if row["status"] == "running":
            return row["poll_epoch"]
    return None


def _polls(rows: list[dict]) -> list[float]:
    return sorted({row["poll_epoch"] for row in rows})


def retry_events(
    rows: list[dict],
    last_poll_epoch: float | None = None,
    poll_epochs: list[float] | None = None,
) -> list[dict]:
    """Every observed sign that a VM needed intervention.

    Four kinds, all edge-triggered so a condition that persists across
    polls counts once:

    - ``reboot``            reboot_count increased
    - ``unhealthy``         healthy went Healthy -> Unhealthy
    - ``status_regression``  status left 'running' after having reached it
    - ``disappeared``       the row stopped appearing while the arm ran
    """
    events: list[dict] = []
    polls = sorted(set(poll_epochs if poll_epochs is not None else _polls(rows)))
    if last_poll_epoch is not None and last_poll_epoch not in polls:
        polls.append(last_poll_epoch)
        polls.sort()
    for hostname, host_rows in by_host(rows).items():
        previous = None
        reached_running = False
        for row in host_rows:
            if previous is not None:
                if row["reboot_count"] > previous["reboot_count"]:
                    events.append(
                        {
                            "hostname": hostname,
                            "epoch": row["poll_epoch"],
                            "kind": "reboot",
                        }
                    )
                if previous["healthy"] == "Healthy" and row["healthy"] == "Unhealthy":
                    events.append(
                        {
                            "hostname": hostname,
                            "epoch": row["poll_epoch"],
                            "kind": "unhealthy",
                        }
                    )
                if reached_running and row["status"] != "running":
                    events.append(
                        {
                            "hostname": hostname,
                            "epoch": row["poll_epoch"],
                            "kind": "status_regression",
                        }
                    )
            reached_running = reached_running or row["status"] == "running"
            previous = row
        present = {row["poll_epoch"] for row in host_rows}
        was_present = False
        first_seen = host_rows[0]["poll_epoch"]
        for poll_epoch in polls:
            if poll_epoch < first_seen:
                continue
            is_present = poll_epoch in present
            if was_present and not is_present:
                events.append(
                    {
                        "hostname": hostname,
                        "epoch": poll_epoch,
                        "kind": "disappeared",
                    }
                )
            was_present = is_present
    events.sort(key=lambda e: (e["epoch"], e["hostname"], e["kind"]))
    return events


def terminal_states(rows: list[dict]) -> dict[str, dict]:
    """Last observed state per host, including hosts that never readied."""
    return {
        hostname: {
            "status": host_rows[-1]["status"],
            "healthy": host_rows[-1]["healthy"],
            "ready": readiness_epoch(host_rows) is not None,
            "last_poll_epoch": host_rows[-1]["poll_epoch"],
        }
        for hostname, host_rows in by_host(rows).items()
    }


def time_to_all_ready(
    rows: list[dict], launch_epoch: float, expected_n: int | None = None
) -> float | None:
    """Seconds from launch to the LAST host readying.

    None if any host never readied. Taking the max over only the hosts
    that made it would make a partly failed arm look faster than a clean
    one, which is the opposite of what panel C claims.
    """
    all_hosts = by_host(rows)
    intended_n = expected_n if expected_n is not None else len(all_hosts)
    hosts = intended_by_host(rows, intended_n)
    if len(hosts) != intended_n:
        return None
    readiness = [readiness_epoch(r) for r in hosts.values()]
    if not readiness or any(value is None for value in readiness):
        return None
    return max(readiness) - launch_epoch


def arm_summary(
    rows: list[dict],
    launch_epoch: float,
    expected_n: int | None = None,
    last_poll_epoch: float | None = None,
    poll_epochs: list[float] | None = None,
) -> dict:
    """One row per arm-replicate for panels C and D."""
    all_hosts = by_host(rows)
    intended = expected_n if expected_n is not None else len(all_hosts)
    hosts = intended_by_host(rows, intended)
    terminal = terminal_states(
        [row for host_rows in hosts.values() for row in host_rows]
    )
    events = retry_events(
        rows, last_poll_epoch=last_poll_epoch, poll_epochs=poll_epochs
    )
    startups = sorted(
        value
        for value in (
            next(
                (
                    r["total_startup_s"]
                    for r in host_rows
                    if r["total_startup_s"] is not None
                ),
                None,
            )
            for host_rows in hosts.values()
        )
        if value is not None
    )
    first = next(iter(rows), {})
    n_ready = sum(1 for state in terminal.values() if state["ready"])
    n_missing = max(0, intended - len(hosts))
    n_never_ready = intended - n_ready
    retried_hosts = {event["hostname"] for event in events if event["kind"] == "reboot"}
    retried_hosts.intersection_update(hosts)
    unstable_hosts = set()
    for event in events:
        hostname = event["hostname"]
        if hostname not in hosts or event["kind"] not in {
            "unhealthy",
            "status_regression",
            "disappeared",
        }:
            continue
        ready_epoch = readiness_epoch(hosts[hostname])
        if ready_epoch is not None and event["epoch"] >= ready_epoch:
            unstable_hosts.add(hostname)
    return {
        "arm_n": first.get("arm_n"),
        "replicate": first.get("replicate"),
        "expected_n": intended,
        "n_hosts": len(all_hosts),
        "n_ready": n_ready,
        "n_missing": n_missing,
        "n_never_ready": n_never_ready,
        "n_disappeared": sum(1 for e in events if e["kind"] == "disappeared"),
        "n_retry_events": len(events),
        "n_retried": len(retried_hosts),
        "n_unstable": len(unstable_hosts),
        "retry_rate": len(retried_hosts) / intended if intended else None,
        "instability_rate": len(unstable_hosts) / intended if intended else None,
        "failure_rate": n_never_ready / intended if intended else None,
        "time_to_all_ready_s": time_to_all_ready(
            rows, launch_epoch, expected_n=intended
        ),
        "startup_median_s": statistics.median(startups) if startups else None,
        "startup_min_s": startups[0] if startups else None,
        "startup_max_s": startups[-1] if startups else None,
    }
