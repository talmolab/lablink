#!/usr/bin/env python3
"""Validate Fig. 2 arm data and render the timeline/scaling figure."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

from protocol import (
    ARM_SIZES,
    MAX_CONSECUTIVE_POLL_ERRORS,
    READY_TIMEOUT_S,
    REPLICATE_ORDERS,
)
from trajectory import (
    arm_summary,
    intended_by_host,
    load_trajectory,
    readiness_epoch,
)


def load_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _load_operations(path: Path) -> list[dict]:
    if not path.exists():
        return []
    float_fields = {"poll_epoch", "created_epoch", "started_epoch", "finished_epoch"}
    int_fields = {"operation_id", "resources_total", "resources_completed"}
    rows = []
    with path.open(newline="") as handle:
        for source in csv.DictReader(handle):
            row = dict(source)
            for field in float_fields:
                value = (row.get(field) or "").strip()
                row[field] = float(value) if value and value != "None" else None
            for field in int_fields:
                value = (row.get(field) or "").strip()
                row[field] = int(float(value)) if value and value != "None" else None
            rows.append(row)
    return rows


def latest_operations(rows: list[dict]) -> list[dict]:
    """Collapse repeated operation snapshots to the last observed state."""
    latest: dict[int, dict] = {}
    for row in rows:
        operation_id = row["operation_id"]
        previous = latest.get(operation_id)
        if previous is None or row["poll_epoch"] >= previous["poll_epoch"]:
            latest[operation_id] = row
    return [latest[key] for key in sorted(latest)]


def provisioning_duration(operations: list[dict], launch_epoch: float) -> float | None:
    """Duration of the completed apply submitted by this arm."""
    candidates = [
        row
        for row in operations
        if row["op_type"] == "apply"
        and row["created_epoch"] is not None
        and row["created_epoch"] >= launch_epoch - 5.0
        and row["started_epoch"] is not None
        and row["finished_epoch"] is not None
        and row["status"] == "succeeded"
    ]
    if not candidates:
        return None
    operation = min(candidates, key=lambda row: row["created_epoch"])
    return operation["finished_epoch"] - operation["started_epoch"]


def _event_epoch(events: list[dict], phase: str) -> float | None:
    return next(
        (float(event["epoch"]) for event in events if event["phase"] == phase),
        None,
    )


def _last_successful_poll(
    path: Path, *, before_epoch: float | None = None
) -> float | None:
    epochs = _successful_poll_epochs(path, before_epoch=before_epoch)
    return max(epochs) if epochs else None


def _successful_poll_epochs(
    path: Path, *, before_epoch: float | None = None
) -> list[float]:
    if not path.exists():
        return []
    epochs = []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            epoch = float(row["poll_epoch"])
            if (row.get("ok") or "").lower() == "true" and (
                before_epoch is None or epoch < before_epoch
            ):
                epochs.append(epoch)
    return sorted(set(epochs))


def _collector_health(
    path: Path,
    *,
    launch_epoch: float,
    end_epoch: float | None,
    poll_interval_s: float,
) -> tuple[bool, str]:
    if not path.exists():
        return False, "poll ledger missing"
    window = []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            epoch = float(row["poll_epoch"])
            if epoch >= launch_epoch and (end_epoch is None or epoch < end_epoch):
                window.append((epoch, (row.get("ok") or "").lower() == "true"))
    if not window:
        return False, "no polls during attempted arm"
    consecutive_errors = 0
    max_errors = 0
    successes = []
    for epoch, ok in sorted(window):
        if ok:
            successes.append(epoch)
            consecutive_errors = 0
        else:
            consecutive_errors += 1
            max_errors = max(max_errors, consecutive_errors)
    if not successes:
        return False, "no successful polls during attempted arm"
    if max_errors > MAX_CONSECUTIVE_POLL_ERRORS:
        return False, f"{max_errors} consecutive poll errors"
    maximum_gap = max(20.0, 3 * poll_interval_s)
    boundaries = [launch_epoch, *successes]
    if end_epoch is not None:
        boundaries.append(end_epoch)
    if any(
        right - left > maximum_gap for left, right in zip(boundaries, boundaries[1:])
    ):
        return False, f"poll coverage gap exceeds {maximum_gap:g}s"
    return True, "ok"


def summarize_run(run_dir: Path) -> dict:
    meta = json.loads((run_dir / "meta.json").read_text())
    events = load_events(run_dir / "events.jsonl")
    launch_epoch = _event_epoch(events, "launch_requested")
    attempted = bool(meta.get("attempted")) and launch_epoch is not None
    analysis_launch_epoch = (
        launch_epoch if launch_epoch is not None else float(meta["started_epoch"])
    )

    trajectory_path = run_dir / "trajectory.csv"
    rows = load_trajectory(trajectory_path) if trajectory_path.exists() else []
    teardown_epoch = _event_epoch(events, "client_destroy_started")
    poll_epochs = _successful_poll_epochs(
        run_dir / "polls.csv", before_epoch=teardown_epoch
    )
    summary = arm_summary(
        rows,
        analysis_launch_epoch,
        expected_n=int(meta["arm_n"]),
        last_poll_epoch=max(poll_epochs) if poll_epochs else None,
        poll_epochs=poll_epochs,
    )
    summary.update(
        {
            "run_dir": run_dir,
            "status": meta["status"],
            "arm_n": int(meta["arm_n"]),
            "replicate": int(meta["replicate"]),
            "image_digest": meta["image_digest"],
            "launch_epoch": launch_epoch,
            "ready_timeout_s": float(meta.get("ready_timeout_s", READY_TIMEOUT_S)),
            "events": events,
        }
    )
    summary["ready_times_s"] = sorted(
        value - analysis_launch_epoch
        for host_rows in intended_by_host(rows, int(meta["arm_n"])).values()
        if (value := readiness_epoch(host_rows)) is not None
    )
    operations = latest_operations(_load_operations(run_dir / "operations.csv"))
    summary["provisioning_time_s"] = provisioning_duration(
        operations, analysis_launch_epoch
    )
    current_apply = [
        row
        for row in operations
        if row["op_type"] == "apply"
        and row["created_epoch"] is not None
        and row["created_epoch"] >= analysis_launch_epoch - 5.0
    ]
    summary["operation_failed"] = any(
        row["status"] in {"failed", "interrupted"} for row in current_apply
    )
    completed_apply = next(
        (
            row
            for row in current_apply
            if row["started_epoch"] is not None and row["finished_epoch"] is not None
        ),
        None,
    )
    summary["apply_started_epoch"] = (
        completed_apply["started_epoch"] if completed_apply else None
    )
    summary["apply_finished_epoch"] = (
        completed_apply["finished_epoch"] if completed_apply else None
    )
    collector_valid, collector_reason = _collector_health(
        run_dir / "polls.csv",
        launch_epoch=analysis_launch_epoch,
        end_epoch=teardown_epoch,
        poll_interval_s=float(meta.get("poll_interval_s", 0)),
    )
    summary["attempted"] = attempted
    summary["collector_valid"] = collector_valid
    summary["collector_reason"] = collector_reason
    summary["analysis_eligible"] = (
        attempted and collector_valid and meta.get("status") in {"complete", "failed"}
    )
    summary["metadata"] = meta
    return summary


def discover_runs(data_dir: Path) -> list[Path]:
    runs = sorted(path.parent for path in data_dir.glob("*/meta.json"))
    if not runs:
        raise ValueError(f"no arm metadata found under {data_dir}")
    digests = {
        json.loads((run / "meta.json").read_text())["image_digest"] for run in runs
    }
    if len(digests) != 1:
        raise ValueError(f"mixed image digests are not comparable: {sorted(digests)}")
    return runs


def validate_dataset(summaries: list[dict], *, allow_incomplete: bool) -> None:
    ineligible = [
        (row["run_dir"].name, row["collector_reason"])
        for row in summaries
        if not row["analysis_eligible"]
    ]
    if ineligible:
        raise ValueError(f"dataset contains analysis-ineligible arms: {ineligible}")
    identities = [(row["arm_n"], row["replicate"]) for row in summaries]
    if len(identities) != len(set(identities)):
        raise ValueError("duplicate N/replicate arm metadata")
    expected = {
        (arm_n, replicate)
        for replicate, order in enumerate(REPLICATE_ORDERS, start=1)
        for arm_n in order
    }
    extras = sorted(set(identities) - expected)
    if extras:
        raise ValueError(f"dataset contains unexpected arms: {extras}")
    frozen_fields = (
        "image_digest",
        "config_sha256",
        "lablink_sha",
        "template_sha",
        "instance_type",
        "region",
        "poll_interval_s",
        "ready_timeout_s",
        "soak_seconds",
    )
    for field in frozen_fields:
        values = {
            json.dumps(row["metadata"].get(field), sort_keys=True) for row in summaries
        }
        if len(values) != 1:
            raise ValueError(f"mixed {field} values across arms")
    for replicate, expected_order in enumerate(REPLICATE_ORDERS, start=1):
        actual_order = tuple(
            row["arm_n"]
            for row in sorted(
                (row for row in summaries if row["replicate"] == replicate),
                key=lambda row: row["metadata"]["started_epoch"],
            )
        )
        expected_partial = tuple(n for n in expected_order if n in actual_order)
        if actual_order and actual_order != expected_partial:
            raise ValueError(
                f"replicate {replicate} order {actual_order} != {expected_partial}"
            )
    if allow_incomplete:
        return
    missing = sorted(expected - set(identities))
    if missing:
        raise ValueError(f"dataset is incomplete; missing arms: {missing}")


def _timeline(ax, events: list[dict]) -> None:
    pairs = [
        ("Configure", "configure_started", "configure_finished", "#9ca3af"),
        ("Deploy", "deploy_started", "deploy_finished", "#64748b"),
        ("Client apply", "apply_started", "apply_finished", "#2563eb"),
        ("Boot to ready", "apply_finished", "all_vms_ready", "#0891b2"),
        ("Claim seats", "claim_burst_started", "claim_burst_finished", "#0d9488"),
        ("Workshop", "soak_started", "soak_finished", "#f59e0b"),
        (
            "Teardown VMs",
            "client_destroy_started",
            "client_destroy_finished",
            "#dc2626",
        ),
        (
            "Destroy allocator",
            "allocator_destroy_started",
            "allocator_destroy_finished",
            "#7c3aed",
        ),
    ]
    available = []
    for label, start_name, end_name, color in pairs:
        start = _event_epoch(events, start_name)
        end = _event_epoch(events, end_name)
        if start is not None and end is not None and end >= start:
            available.append((label, start, end, color))
    if not available:
        ax.text(0.5, 0.5, "No complete exemplar timeline", ha="center", va="center")
        ax.set_axis_off()
        return
    origin = min(start for _, start, _, _ in available)
    for index, (label, start, end, color) in enumerate(available):
        x = start - origin
        width = end - start
        ax.broken_barh([(x, max(width, 0.2))], (0.25, 0.5), facecolors=color)
        ax.text(
            x + width / 2,
            0.82 + 0.14 * (index % 2),
            f"{width:.0f}s",
            ha="center",
            va="bottom",
            fontsize=8,
        )
        ax.text(
            x + width / 2,
            0.5,
            label,
            ha="center",
            va="center",
            color="white",
            fontsize=8,
            fontweight="bold",
        )
    ax.set_ylim(0.1, 1.2)
    ax.set_yticks([])
    ax.set_xlabel("Elapsed wall time (s)")
    ax.spines[["left", "right", "top"]].set_visible(False)


def _grouped(summaries: list[dict]) -> dict[int, list[dict]]:
    return {
        arm_n: sorted(
            [row for row in summaries if row["arm_n"] == arm_n],
            key=lambda row: row["replicate"],
        )
        for arm_n in ARM_SIZES
    }


def render_figure(
    summaries: list[dict],
    timeline_events: list[dict],
    dashboard: Path,
    output_prefix: Path,
) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    grouped = _grouped(summaries)
    fig = plt.figure(figsize=(13, 10), constrained_layout=True)
    grid = fig.add_gridspec(3, 2, height_ratios=(0.8, 1.3, 1.15))
    ax_a = fig.add_subplot(grid[0, :])
    ax_b = fig.add_subplot(grid[1, 0])
    ax_c = fig.add_subplot(grid[1, 1])
    ax_d = fig.add_subplot(grid[2, 0])
    ax_inset = fig.add_subplot(grid[2, 1])

    ax_a.set_title("A  One workshop, start to finish", loc="left", fontweight="bold")
    _timeline(ax_a, timeline_events)

    positions = np.arange(len(ARM_SIZES))
    provisioning = [
        [
            row["provisioning_time_s"]
            for row in grouped[n]
            if row["provisioning_time_s"] is not None
        ]
        for n in ARM_SIZES
    ]
    if any(provisioning):
        safe = [values if values else [math.nan] for values in provisioning]
        ax_b.boxplot(safe, positions=positions, widths=0.5, showfliers=False)
        for x, values in zip(positions, provisioning):
            offsets = np.linspace(-0.12, 0.12, len(values)) if values else []
            ax_b.scatter(x + offsets, values, color="#2563eb", zorder=3)
    ax_b.set_xticks(positions, ARM_SIZES)
    ax_b.set_xlabel("Intended VMs (N)")
    ax_b.set_ylabel("Apply operation duration (s)")
    ax_b.set_title("B  Provisioning time", loc="left", fontweight="bold")
    ax_b.grid(axis="y", alpha=0.25)

    for x, arm_n in zip(positions, ARM_SIZES):
        ready = [value for row in grouped[arm_n] for value in row["ready_times_s"]]
        if ready:
            offsets = np.linspace(-0.18, 0.18, len(ready))
            ax_c.scatter(x + offsets, ready, s=18, alpha=0.65, color="#0d9488")
        all_ready = [
            row["time_to_all_ready_s"]
            for row in grouped[arm_n]
            if row["time_to_all_ready_s"] is not None
        ]
        if all_ready:
            ax_c.scatter(
                [x] * len(all_ready),
                all_ready,
                marker="D",
                s=48,
                color="#0f172a",
                label="all ready" if x == 0 else None,
            )
        failed = sum(row["n_never_ready"] for row in grouped[arm_n])
        if failed:
            timeout = max(row["ready_timeout_s"] for row in grouped[arm_n])
            ax_c.scatter(x, timeout, marker="x", s=70, color="#dc2626")
            ax_c.text(x, timeout, f" {failed} failed", fontsize=8, color="#dc2626")
    ax_c.set_xticks(positions, ARM_SIZES)
    ax_c.set_xlabel("Intended VMs (N)")
    ax_c.set_ylabel("Launch request to seat-ready (s)")
    ax_c.set_title("C  Time to ready", loc="left", fontweight="bold")
    ax_c.grid(axis="y", alpha=0.25)

    failure_rates = []
    retry_rates = []
    instability_rates = []
    failure_counts = []
    retry_counts = []
    instability_counts = []
    denominators = []
    for arm_n in ARM_SIZES:
        arms = grouped[arm_n]
        denominator = sum(row["expected_n"] for row in arms)
        failure_count = sum(row["n_never_ready"] for row in arms)
        retry_count = sum(row["n_retried"] for row in arms)
        instability_count = sum(row.get("n_unstable", 0) for row in arms)
        denominators.append(denominator)
        failure_counts.append(failure_count)
        retry_counts.append(retry_count)
        instability_counts.append(instability_count)
        failure_rates.append(failure_count / denominator if denominator else 0)
        retry_rates.append(retry_count / denominator if denominator else 0)
        instability_rates.append(instability_count / denominator if denominator else 0)
    width = 0.24
    failure_bars = ax_d.bar(
        positions - width,
        failure_rates,
        width,
        label="Failure rate",
        color="#dc2626",
    )
    retry_bars = ax_d.bar(
        positions, retry_rates, width, label="Reboot rate", color="#f59e0b"
    )
    instability_bars = ax_d.bar(
        positions + width,
        instability_rates,
        width,
        label="Post-ready instability",
        color="#7c3aed",
    )
    ax_d.set_xticks(positions, ARM_SIZES)
    ax_d.set_xlabel("Intended VMs (N)")
    ax_d.set_ylabel("Fraction of intended VMs")
    ax_d.set_ylim(
        0,
        max(
            0.05,
            max(failure_rates + retry_rates + instability_rates, default=0) * 1.35,
        ),
    )
    ax_d.set_title("D  Failures and retries", loc="left", fontweight="bold")
    ax_d.bar_label(
        failure_bars,
        labels=[
            f"{count}/{total}" for count, total in zip(failure_counts, denominators)
        ],
        padding=3,
        fontsize=8,
    )
    ax_d.bar_label(
        retry_bars,
        labels=[f"{count}/{total}" for count, total in zip(retry_counts, denominators)],
        padding=3,
        fontsize=8,
    )
    ax_d.bar_label(
        instability_bars,
        labels=[
            f"{count}/{total}" for count, total in zip(instability_counts, denominators)
        ],
        padding=3,
        fontsize=8,
    )
    operation_failures = sum(row.get("operation_failed", False) for row in summaries)
    failed_arms = sum(row.get("status") == "failed" for row in summaries)
    ax_d.text(
        0.99,
        0.95,
        f"Failed arms: {failed_arms}/{len(summaries)}; "
        f"failed/interrupted applies: {operation_failures}/{len(summaries)}",
        transform=ax_d.transAxes,
        ha="right",
        va="top",
        fontsize=8,
    )
    ax_d.legend(frameon=False)
    ax_d.grid(axis="y", alpha=0.25)

    image = plt.imread(dashboard)
    ax_inset.imshow(image)
    ax_inset.set_title(
        "Live admin dashboard (annotated)", loc="left", fontweight="bold"
    )
    annotations = [
        ("Pool size", (0.15, 0.12), (0.02, 0.02)),
        ("Ready status", (0.52, 0.33), (0.78, 0.08)),
        ("Startup timing", (0.70, 0.58), (0.77, 0.86)),
        ("Seat claims", (0.32, 0.74), (0.02, 0.91)),
    ]
    for label, target, text_pos in annotations:
        ax_inset.annotate(
            label,
            xy=target,
            xycoords="axes fraction",
            xytext=text_pos,
            textcoords="axes fraction",
            fontsize=8,
            color="white",
            bbox={"boxstyle": "round,pad=0.25", "fc": "#0f172a", "alpha": 0.85},
            arrowprops={"arrowstyle": "->", "color": "#facc15", "lw": 1.5},
        )
    ax_inset.set_axis_off()

    fig.suptitle(
        "One LabLink workshop, scaling from 5 to 60 seats",
        fontsize=16,
        fontweight="bold",
    )
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_prefix.with_suffix(".png"), dpi=300, bbox_inches="tight")
    fig.savefig(output_prefix.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--timeline-events", type=Path, action="append", default=[])
    parser.add_argument("--dashboard", type=Path, required=True)
    parser.add_argument("--out-prefix", type=Path, required=True)
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()

    if not args.dashboard.is_file():
        parser.error(f"dashboard screenshot does not exist: {args.dashboard}")
    run_dirs = discover_runs(args.data_dir)
    summaries = [summarize_run(path) for path in run_dirs]
    validate_dataset(summaries, allow_incomplete=args.allow_incomplete)
    events = []
    for path in args.timeline_events:
        events.extend(load_events(path))
    if not events:
        exemplar = next((row for row in summaries if row["arm_n"] == 30), summaries[0])
        events = exemplar["events"]
    else:
        exemplar = next(
            (row for row in summaries if row["arm_n"] == 60 and row["replicate"] == 1),
            summaries[0],
        )
    if exemplar.get("apply_started_epoch") is not None:
        events.extend(
            [
                {"phase": "apply_started", "epoch": exemplar["apply_started_epoch"]},
                {"phase": "apply_finished", "epoch": exemplar["apply_finished_epoch"]},
            ]
        )
    events.sort(key=lambda event: event["epoch"])
    render_figure(summaries, events, args.dashboard, args.out_prefix)
    sidecar = {
        "image_digest": summaries[0]["image_digest"],
        "run_directories": [str(path) for path in run_dirs],
        "arm_sizes": list(ARM_SIZES),
        "replicates": len(REPLICATE_ORDERS),
        "frozen_metadata": {
            field: summaries[0]["metadata"].get(field)
            for field in (
                "config_sha256",
                "lablink_sha",
                "template_sha",
                "instance_type",
                "region",
                "poll_interval_s",
                "ready_timeout_s",
                "soak_seconds",
            )
        },
        "runs": [summary["metadata"] for summary in summaries],
    }
    args.out_prefix.with_suffix(".json").write_text(
        json.dumps(sidecar, indent=2, sort_keys=True) + "\n"
    )
    print(
        f"wrote {args.out_prefix.with_suffix('.png')} and "
        f"{args.out_prefix.with_suffix('.pdf')}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
