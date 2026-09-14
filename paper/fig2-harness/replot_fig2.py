#!/usr/bin/env python3
"""Fig 2 (redesigned) — workshop scaling, from the post-fix rep-1 runs.

Panels:
  A  Prep timeline (one representative workshop): cold allocator deploy ->
     client apply -> boot to a ready 30-seat pool.
  B  Per-VM time from the operator's `lablink client launch` command (against
     an already-deployed allocator) to the allocator marking the VM ready to
     be assigned, vs N (bar = median, whisker = IQR).
  C  Outcome per VM vs N, stacked: succeeded / recovered (reboot) / failed.

Metrics reuse the harness definitions (trajectory.readiness_epoch is the
collector-clock first-running observation, differenced against the local
launch_requested epoch — no cross-machine subtraction).

Usage: uv run --with matplotlib python replot_fig2.py
"""

from __future__ import annotations

import json
import statistics as st
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import MaxNLocator  # noqa: E402

from trajectory import intended_by_host, load_trajectory, readiness_epoch  # noqa: E402

HERE = Path(__file__).resolve().parent  # run directories live next to this script
ARMS = {
    5: HERE / "data/n005-r1-7a827c7b65",
    10: HERE / "data/n010-r1-3330bd815f",
    30: HERE / "data/n030-r1-e0596dd0ab",
    60: HERE / "data/n060-r1-f29a57c79e",  # polling gaps: see its POLLING-GAPS.md
}
EXEMPLAR_N = 30
DEPLOY_S = 125.7  # this allocator's real cold deploy (deployments cache)

# --- palette (validated: CVD ΔE 10.8; labels supply the amber's contrast relief)
INK, INK2, MUTED = "#1a1a1a", "#5a6472", "#838c99"
SERIES = "#2166ac"  # client-VM provisioning (single-series magnitude)
S_OK, S_RETRY, S_FAIL = "#4a9d6a", "#e6a532", "#b2352a"  # status stack
A_DEPLOY, A_APPLY, A_BOOT, A_CLAIM = "#6b7a99", "#5b9bd5", "#2166ac", "#1baf7a"


def _launch_epoch(run_dir: str) -> float:
    for line in open(Path(run_dir) / "events.jsonl"):
        event = json.loads(line)
        if event.get("phase") == "launch_requested":
            return float(event["epoch"])
    raise ValueError(f"no launch_requested in {run_dir}")


def _phase(run_dir: str, name: str) -> float | None:
    for line in open(Path(run_dir) / "events.jsonl"):
        event = json.loads(line)
        if event.get("phase") == name:
            return float(event["epoch"])
    return None


def _quantile(values: list[float], p: float) -> float:
    values = sorted(values)
    k = (len(values) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def collect() -> dict[int, dict]:
    out: dict[int, dict] = {}
    for n, run_dir in ARMS.items():
        rows = load_trajectory(Path(run_dir) / "trajectory.csv")
        launch = _launch_epoch(run_dir)
        hosts = intended_by_host(rows, n)
        ready = []
        ok = retry = fail = 0
        for host_rows in hosts.values():
            ready_epoch = readiness_epoch(host_rows)
            if ready_epoch is None:
                fail += 1
                continue
            ready.append(ready_epoch - launch)
            reboots = max((r.get("reboot_count") or 0) for r in host_rows)
            if reboots > 0:
                retry += 1
            else:
                ok += 1
        out[n] = {
            "ready": ready,
            "ok": ok,
            "retry": retry,
            "fail": fail,
        }
    return out


def _bars_median_iqr(ax, ns, series_by_n, key, ylabel, title, unit="s"):
    xs = list(range(len(ns)))
    ymax = max(_quantile(series_by_n[n][key], 0.75) for n in ns) * 1.28
    ax.set_ylim(0, ymax)
    for x, n in zip(xs, ns):
        vals = series_by_n[n][key]
        median = st.median(vals)
        q1, q3 = _quantile(vals, 0.25), _quantile(vals, 0.75)
        ax.bar(x, median, width=0.62, color=SERIES, edgecolor="white",
               linewidth=1.2, zorder=2)
        # IQR whisker (middle 50%): brackets the median at the bar top
        ax.plot([x, x], [q1, q3], color=INK, lw=1.6, zorder=4,
                solid_capstyle="round")
        for y in (q1, q3):
            ax.plot([x - 0.07, x + 0.07], [y, y], color=INK, lw=1.6, zorder=4)
        ax.text(x, q3 + ymax * 0.015, f"{median:.0f}{unit}",
                ha="center", va="bottom", fontsize=8.5, color=INK2, zorder=5)
    ax.set_xticks(xs)
    ax.set_xticklabels([str(n) for n in ns])
    ax.set_xlabel("Pool size  N (VMs)", fontsize=9.5, color=INK2)
    ax.set_ylabel(ylabel, fontsize=9.5, color=INK2)
    ax.set_title(title, loc="left", fontsize=11, fontweight="bold", color=INK)
    _despine(ax)


def _stack_outcomes(ax, ns, series_by_n):
    xs = list(range(len(ns)))
    segs = [("Succeeded", "ok", S_OK), ("Recovered (reboot)", "retry", S_RETRY),
            ("Failed", "fail", S_FAIL)]
    for x, n in zip(xs, ns):
        bottom = 0.0
        for _, key, color in segs:
            v = series_by_n[n][key]
            if v <= 0:
                continue
            ax.bar(x, v, width=0.62, bottom=bottom, color=color, edgecolor="white",
                   linewidth=1.4, zorder=2)
            ax.text(x, bottom + v / 2, str(v), ha="center", va="center",
                    fontsize=8.5, color="white", fontweight="bold", zorder=5)
            bottom += v
        ax.text(x, bottom, f"{n}/{n}", ha="center", va="bottom", fontsize=8.5,
                color=INK2, zorder=5)
    ax.set_xticks(xs)
    ax.set_xticklabels([str(n) for n in ns])
    ax.set_xlabel("Pool size  N (VMs)", fontsize=9.5, color=INK2)
    ax.set_ylabel("Client VMs", fontsize=9.5, color=INK2)
    ax.set_title("C   VM outcomes by pool size",
                 loc="left", fontsize=11, fontweight="bold", color=INK)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax.set_ylim(0, max(ns) * 1.12)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for _, _, c in segs]
    ax.legend(handles, [s for s, _, _ in segs], frameon=False, fontsize=8.5,
              loc="upper left", ncol=1, handlelength=1.1, labelcolor=INK2)
    _despine(ax)


def _prep_timeline(ax, run_dir):
    apply_s = (_phase(run_dir, "launch_finished") or 0) - (
        _phase(run_dir, "launch_started") or 0)
    boot_s = (_phase(run_dir, "all_vms_ready") or 0) - (
        _phase(run_dir, "launch_finished") or 0)
    segs = [("Allocator deploy", DEPLOY_S, A_DEPLOY),
            ("Client apply", apply_s, A_APPLY),
            ("Boot to ready", boot_s, A_BOOT)]
    total = sum(s for _, s, _ in segs)
    left = 0.0
    for label, width, color in segs:
        ax.barh(0, width, left=left, height=0.5, color=color, edgecolor="white",
                linewidth=1.5, zorder=2)
        ax.text(left + width / 2, 0, f"{label}\n{width:.0f}s", ha="center",
                va="center", fontsize=8.5, color="white", fontweight="bold",
                zorder=4)
        left += width
    # "pool ready" marker
    ax.plot([total, total], [-0.28, 0.28], color=INK, lw=1.4, zorder=5)
    ax.scatter([total], [0], s=1, zorder=5)
    ax.annotate(f"Pool ready\n{EXEMPLAR_N} seats",
                xy=(total, 0.28), xytext=(total, 0.62), ha="center", fontsize=8.5,
                color=INK, fontweight="bold")
    ax.set_xlim(-total * 0.02, total * 1.18)
    ax.set_ylim(-0.45, 0.95)
    ax.set_yticks([])
    ax.set_xlabel("Elapsed wall time (s)", fontsize=9.5, color=INK2)
    ax.set_title(
        f"A   Workshop prep timeline ({EXEMPLAR_N}-seat pool)",
        loc="left", fontsize=11, fontweight="bold", color=INK)
    for side in ("left", "right", "top"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(MUTED)
    ax.tick_params(colors=INK2, labelsize=9)


def _despine(ax):
    for side in ("right", "top"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=INK2, labelsize=9)


def main():
    data = collect()
    ns = sorted(ARMS)
    fig = plt.figure(figsize=(11, 9.8))
    gs = fig.add_gridspec(3, 2, height_ratios=[0.92, 1.5, 1.4], hspace=0.6,
                          wspace=0.24, left=0.07, right=0.97, top=0.9, bottom=0.16)
    fig.suptitle("Workshop-scale benchmark (5–60 seats)", x=0.07,
                 ha="left", fontsize=15, fontweight="bold", color=INK, y=0.965)

    _prep_timeline(fig.add_subplot(gs[0, :]), ARMS[EXEMPLAR_N])
    _bars_median_iqr(fig.add_subplot(gs[1, :]), ns, data, "ready",
                     "lablink client launch → VM ready (s)",
                     "B   Median time to ready by pool size")
    _stack_outcomes(fig.add_subplot(gs[2, :]), ns, data)

    out = HERE.parent / "fig2.png"  # the figure the paper embeds
    fig.savefig(out, dpi=300, bbox_inches="tight")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
