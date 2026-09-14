#!/usr/bin/env python3
"""Poll the allocator's VM table and append each snapshot to a trajectory CSV.

The trajectory -- not the final table -- is the data source for three of
Fig 2's four panels. The VM table holds only terminal state, so a VM that
failed and was replaced leaves no row at all; the June 2026 workshop's
"0 reboots out of 26" is that artifact, not a measurement.

Usage:
    ALLOCATOR_HOST=<ec2-public-dns> SSH_KEY=~/.ssh/lablink.pem \\
    uv run paper/fig2-harness/poll_pool.py \\
        --arm-n 60 --replicate 1 \\
        --image-digest sha256:... \\
        --out paper/fig2-harness/data/arm-60-rep1-trajectory.csv
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from protocol import DEFAULT_POLL_INTERVAL_S

POLL_INTERVAL_S = DEFAULT_POLL_INTERVAL_S

# Column names as the CURRENT schema spells them. The pre-rename export
# said `terraformapplystarttime`; generate_init_sql.py now says
# TofuApplyStartTime, which Postgres folds to lowercase.
REQUIRED_COLUMNS = [
    "hostname",
    "status",
    "healthy",
    "reboot_count",
    "tofuapplystarttime",
    "tofuapplyendtime",
    "cloudinitstarttime",
    "cloudinitendtime",
    "containerstarttime",
    "containerendtime",
    "totalstartupdurationseconds",
    "createdat",
    "sessionstartedat",
    "last_seen_at",
    "machine_identity",
]

SNAPSHOT_SQL = (
    "COPY (SELECT hostname, status, healthy, COALESCE(reboot_count, 0) "
    "AS reboot_count, tofuapplystarttime, tofuapplyendtime, "
    "cloudinitstarttime, cloudinitendtime, containerstarttime, "
    "containerendtime, totalstartupdurationseconds, createdat, "
    "sessionstartedat, last_seen_at, machine_identity FROM vms ORDER BY hostname) "
    "TO STDOUT WITH CSV HEADER"
)

OPERATION_SQL = (
    "COPY (SELECT id, op_type, status, created_at, started_at, finished_at, "
    "error, resources_total, resources_completed FROM operations "
    "ORDER BY id) TO STDOUT WITH CSV HEADER"
)

POLL_COLUMNS = [
    "poll_epoch",
    "arm_n",
    "replicate",
    "image_digest",
    "observed_hosts",
    "ok",
    "error",
    "operations_ok",
    "operations_error",
]

OPERATION_COLUMNS = [
    "poll_epoch",
    "arm_n",
    "replicate",
    "image_digest",
    "operation_id",
    "op_type",
    "status",
    "created_epoch",
    "started_epoch",
    "finished_epoch",
    "error",
    "resources_total",
    "resources_completed",
]

TRAJECTORY_COLUMNS = [
    "poll_epoch",
    "arm_n",
    "replicate",
    "image_digest",
    "clock_offset_s",
    "hostname",
    "status",
    "healthy",
    "reboot_count",
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
    "machine_identity",
]

_EPOCH_FIELDS = {
    "tofuapplystarttime": "tofu_start_epoch",
    "tofuapplyendtime": "tofu_end_epoch",
    "cloudinitstarttime": "cloudinit_start_epoch",
    "cloudinitendtime": "cloudinit_end_epoch",
    "containerstarttime": "container_start_epoch",
    "containerendtime": "container_end_epoch",
    "createdat": "created_epoch",
    "sessionstartedat": "session_started_epoch",
    "last_seen_at": "last_seen_epoch",
}


def to_epoch_utc(value: str) -> float | None:
    """Parse a DB timestamp to UTC epoch seconds.

    A naive value is read as UTC. That is the only self-consistent reading:
    the June table's naive phase timestamps, read as local time, put seat
    claims 1.3 hours before the VMs were ready. run_arm.sh records a live
    clock-offset probe so the assumption is checked rather than trusted.
    """
    text = (value or "").strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def preflight_columns(csv_header: str) -> None:
    """Raise if the snapshot header is missing any column we depend on."""
    present = {c.strip().lower() for c in csv_header.strip().split(",")}
    missing = [c for c in REQUIRED_COLUMNS if c not in present]
    if missing:
        raise RuntimeError(
            "VM table snapshot is missing required column(s): "
            + ", ".join(missing)
            + ". Present: "
            + ", ".join(sorted(present))
        )


def parse_snapshot(
    csv_text: str,
    *,
    poll_epoch: float,
    arm_n: int,
    replicate: int,
    image_digest: str,
    clock_offset_s: float,
) -> list[dict]:
    """Turn one snapshot's CSV text into trajectory rows."""
    lines = csv_text.strip().splitlines()
    if not lines:
        return []
    preflight_columns(lines[0])
    rows: list[dict] = []
    for src in csv.DictReader(io.StringIO(csv_text)):
        row = {
            "poll_epoch": poll_epoch,
            "arm_n": arm_n,
            "replicate": replicate,
            "image_digest": image_digest,
            "clock_offset_s": clock_offset_s,
            "hostname": src["hostname"],
            "status": src["status"],
            "healthy": src["healthy"],
            "reboot_count": int(src["reboot_count"] or 0),
            "machine_identity": (src.get("machine_identity") or "").strip() or None,
            "total_startup_s": float(src["totalstartupdurationseconds"])
            if (src["totalstartupdurationseconds"] or "").strip()
            else None,
        }
        for src_key, dest_key in _EPOCH_FIELDS.items():
            row[dest_key] = to_epoch_utc(src[src_key])
        rows.append(row)
    return rows


def append_trajectory(rows: list[dict], out: Path) -> None:
    """Append rows, writing the header only on first touch."""
    out.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out.exists()
    with out.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TRAJECTORY_COLUMNS)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def _append_rows(rows: list[dict], out: Path, columns: list[str]) -> None:
    """Append records with a stable header."""
    out.parent.mkdir(parents=True, exist_ok=True)
    new_file = not out.exists()
    with out.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def append_poll_observation(
    out: Path,
    *,
    poll_epoch: float,
    arm_n: int,
    replicate: int,
    image_digest: str,
    observed_hosts: int,
    ok: bool,
    error: str = "",
    operations_ok: bool = True,
    operations_error: str = "",
) -> None:
    """Record every polling attempt, including empty and failed polls."""
    _append_rows(
        [
            {
                "poll_epoch": poll_epoch,
                "arm_n": arm_n,
                "replicate": replicate,
                "image_digest": image_digest,
                "observed_hosts": observed_hosts,
                "ok": ok,
                "error": error,
                "operations_ok": operations_ok,
                "operations_error": operations_error,
            }
        ],
        out,
        POLL_COLUMNS,
    )


def parse_operation_snapshot(
    csv_text: str,
    *,
    poll_epoch: float,
    arm_n: int,
    replicate: int,
    image_digest: str,
) -> list[dict]:
    """Parse the safe, allowlisted operation history into epoch records."""
    rows: list[dict] = []
    for src in csv.DictReader(io.StringIO(csv_text)):
        rows.append(
            {
                "poll_epoch": poll_epoch,
                "arm_n": arm_n,
                "replicate": replicate,
                "image_digest": image_digest,
                "operation_id": int(src["id"]),
                "op_type": src["op_type"],
                "status": src["status"],
                "created_epoch": to_epoch_utc(src["created_at"]),
                "started_epoch": to_epoch_utc(src["started_at"]),
                "finished_epoch": to_epoch_utc(src["finished_at"]),
                "error": src["error"],
                "resources_total": int(src["resources_total"])
                if (src["resources_total"] or "").strip()
                else None,
                "resources_completed": int(src["resources_completed"])
                if (src["resources_completed"] or "").strip()
                else None,
            }
        )
    return rows


def append_operation_snapshot(rows: list[dict], out: Path) -> None:
    """Append one observed operation-history snapshot."""
    if rows:
        _append_rows(rows, out, OPERATION_COLUMNS)


def _psql_cmd(host: str, ssh_key: str, sql: str) -> list[str]:
    """Build the allocator SSH command for an allowlisted SQL statement."""
    remote = (
        "sudo docker exec --user postgres $(sudo docker ps -q | head -1) "
        f'psql -d lablink_db -X -v ON_ERROR_STOP=1 -c "{sql}"'
    )
    return [
        "ssh",
        "-i",
        ssh_key,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "ConnectTimeout=10",
        f"ubuntu@{host}",
        remote,
    ]


def snapshot_cmd(host: str, ssh_key: str) -> list[str]:
    """SSH command that prints one snapshot as CSV.

    Postgres runs inside the allocator container, and the container has no
    stable name on an AWS deploy -- commands/logs.py:217 resolves it as
    `sudo docker ps -q | head -1`, so we do the same rather than guessing.
    """
    return _psql_cmd(host, ssh_key, SNAPSHOT_SQL)


def operation_snapshot_cmd(host: str, ssh_key: str) -> list[str]:
    """SSH command for safe operation timing/status fields only."""
    return _psql_cmd(host, ssh_key, OPERATION_SQL)


def poll_once(host: str, ssh_key: str) -> str:
    result = subprocess.run(
        snapshot_cmd(host, ssh_key), capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise RuntimeError(f"snapshot failed: {result.stderr.strip()}")
    return result.stdout


def poll_operations_once(host: str, ssh_key: str) -> str:
    result = subprocess.run(
        operation_snapshot_cmd(host, ssh_key),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"operation snapshot failed: {result.stderr.strip()}")
    return result.stdout


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm-n", type=int, required=True)
    parser.add_argument("--replicate", type=int, required=True)
    parser.add_argument("--image-digest", required=True)
    parser.add_argument("--clock-offset-s", type=float, default=0.0)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--polls-out", type=Path)
    parser.add_argument("--operations-out", type=Path)
    parser.add_argument("--interval", type=float, default=POLL_INTERVAL_S)
    args = parser.parse_args()

    polls_out = args.polls_out or args.out.with_name(
        args.out.stem.replace("-trajectory", "") + "-polls.csv"
    )
    operations_out = args.operations_out or args.out.with_name(
        args.out.stem.replace("-trajectory", "") + "-operations.csv"
    )

    host = os.environ["ALLOCATOR_HOST"]
    ssh_key = os.environ["SSH_KEY"]

    # One eager snapshot so a schema problem fails before the arm spends
    # money, rather than at plotting time.
    preflight_columns(poll_once(host, ssh_key).splitlines()[0])
    print(f"preflight ok; polling every {args.interval}s -> {args.out}")

    while True:
        started = time.time()
        rows: list[dict] = []
        operation_rows: list[dict] = []
        vm_error = ""
        operations_error = ""
        try:
            text = poll_once(host, ssh_key)
            observed_epoch = time.time()
            rows = parse_snapshot(
                text,
                poll_epoch=observed_epoch,
                arm_n=args.arm_n,
                replicate=args.replicate,
                image_digest=args.image_digest,
                clock_offset_s=args.clock_offset_s,
            )
            append_trajectory(rows, args.out)
        except Exception as exc:  # a dropped VM poll must not end the arm
            vm_error = str(exc)
            print(f"VM poll at {started:.0f} failed: {exc}", file=sys.stderr)

        try:
            operation_text = poll_operations_once(host, ssh_key)
            operation_observed_epoch = time.time()
            operation_rows = parse_operation_snapshot(
                operation_text,
                poll_epoch=operation_observed_epoch,
                arm_n=args.arm_n,
                replicate=args.replicate,
                image_digest=args.image_digest,
            )
            append_operation_snapshot(operation_rows, operations_out)
        except Exception as exc:  # operation history is independently useful
            operations_error = str(exc)
            print(f"operation poll at {started:.0f} failed: {exc}", file=sys.stderr)

        append_poll_observation(
            polls_out,
            poll_epoch=observed_epoch if not vm_error else time.time(),
            arm_n=args.arm_n,
            replicate=args.replicate,
            image_digest=args.image_digest,
            observed_hosts=len(rows),
            ok=not vm_error,
            error=vm_error,
            operations_ok=not operations_error,
            operations_error=operations_error,
        )
        time.sleep(max(0.0, args.interval - (time.time() - started)))


if __name__ == "__main__":
    sys.exit(main())
