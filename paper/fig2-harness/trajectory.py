#!/usr/bin/env python3
"""Pure derivations over a Fig 2 trajectory CSV.

Everything panels B and C report comes from here. The one rule the
module exists to enforce: a conclusion is drawn from the sequence of
snapshots, never from the last one. The VM table holds terminal state
only, so the last snapshot cannot distinguish "no VM ever failed" from
"the failures were replaced and their rows are gone".
"""

from __future__ import annotations

import csv
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
    early rows with the identity observed for the same hostname and creation
    time so one VM is not counted twice. An unregistered replacement retains
    its own creation-time key when a hostname is reused.
    """
    identities: dict[tuple[str, float], str] = {}
    observations: dict[str, list[tuple[float, str]]] = {}
    for row in rows:
        if row.get("machine_identity"):
            if row.get("created_epoch") is not None:
                identities[(row["hostname"], row["created_epoch"])] = row[
                    "machine_identity"
                ]
            observations.setdefault(row["hostname"], []).append(
                (row["poll_epoch"], row["machine_identity"])
            )
    for host_observations in observations.values():
        host_observations.sort()

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        identity = row.get("machine_identity")
        if not identity:
            created_epoch = row.get("created_epoch")
            if created_epoch is not None:
                identity = identities.get(
                    (row["hostname"], created_epoch),
                    f"{row['hostname']}@{created_epoch}",
                )
            else:
                identity = next(
                    (observed_identity
                     for epoch, observed_identity in observations.get(
                         row["hostname"], []
                     )
                     if epoch >= row["poll_epoch"]),
                    row["hostname"],
                )
        grouped.setdefault(identity, []).append(row)
    for host_rows in grouped.values():
        host_rows.sort(key=lambda r: r["poll_epoch"])
    return grouped


def intended_by_host(rows: list[dict], expected_n: int) -> dict[str, list[dict]]:
    """Select the first observed cohort; later identities are replacements."""
    observed_hostnames = {row["hostname"] for row in rows}
    if len(observed_hostnames) < expected_n:
        raise ValueError(
            f"expected {expected_n} VM hostnames, observed {len(observed_hostnames)}"
        )
    hosts = by_host(rows)
    if len(hosts) < expected_n:
        raise ValueError(
            f"expected {expected_n} VM trajectories, observed {len(hosts)}"
        )
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
