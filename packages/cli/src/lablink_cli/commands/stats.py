"""Render a cohort session-metrics summary in the terminal."""

from __future__ import annotations

import base64
import json
import ssl
import statistics
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rich.console import Console
from rich.table import Table

from lablink_cli.commands.utils import (
    get_allocator_url,
    resolve_admin_credentials,
)

console = Console()


def _fetch(cfg) -> dict:
    allocator_url = get_allocator_url(cfg)
    if not allocator_url:
        console.print("[red]Could not determine allocator URL.[/red]")
        raise SystemExit(1)

    admin_user, admin_pw = resolve_admin_credentials(cfg)
    credentials = base64.b64encode(
        f"{admin_user}:{admin_pw}".encode()
    ).decode()

    req = Request(
        f"{allocator_url}/api/export-metrics?format=json", method="GET"
    )
    req.add_header("Authorization", f"Basic {credentials}")
    req.add_header("Accept", "application/json")

    ctx = ssl.create_default_context()
    if cfg.ssl.provider == "self_signed":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    try:
        resp = urlopen(req, timeout=60, context=ctx)
        return json.loads(resp.read().decode())
    except (HTTPError, URLError) as e:
        console.print(f"[red]Could not reach allocator: {e}[/red]")
        raise SystemExit(1) from e


def _summary(vms: list[dict]) -> dict:
    total = len(vms)
    started = sum(1 for v in vms if v.get("SessionMetricsStartedAt"))
    labeled = sum(1 for v in vms if v.get("SecondsToFirstSleapLabel") is not None)
    trained = sum(1 for v in vms if v.get("SecondsToFirstSleapTrain") is not None)
    tracked = sum(1 for v in vms if v.get("SecondsToFirstSleapTrack") is not None)
    pct_train = (trained / total * 100.0) if total else 0.0
    median_subject = _median_of(vms, "SecondsInSubjectSoftware")
    median_train = _median_of(vms, "SecondsToFirstSleapTrain")
    median_frames = _median_of(vms, "MaxLabeledFrames")
    median_epochs = _median_of(vms, "TrainingEpochsCompleted")
    return {
        "total": total,
        "funnel": {
            "Started": started,
            "Labeled": labeled,
            "Trained": trained,
            "Tracked": tracked,
        },
        "pct_train": pct_train,
        "median_subject": median_subject,
        "median_train": median_train,
        "median_frames": median_frames,
        "median_epochs": median_epochs,
    }


def _subject_label(cfg) -> str:
    """Resolve the display name of the tutorial app from the deployment cfg."""
    patterns = list(
        getattr(getattr(cfg, "monitoring", None), "subject_window_patterns", [])
        or []
    )
    if patterns:
        return patterns[0]
    return getattr(getattr(cfg, "client", None), "software", "") or "subject"


def _median_of(vms: list[dict], key: str):
    vals = [v[key] for v in vms if v.get(key) is not None]
    return statistics.median(vals) if vals else None


def _fmt_hms(seconds: int | float | None) -> str:
    if seconds is None:
        return "—"
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def run_stats(cfg) -> None:
    body = _fetch(cfg)
    vms = body.get("vms", [])
    if not vms:
        console.print(
            "[yellow]No session metrics yet. Either monitoring is disabled "
            "or no VMs have reported.[/yellow]"
        )
        return

    summary = _summary(vms)
    deploy = getattr(cfg, "deployment_name", "lablink")
    console.print(
        f"\n[bold]LabLink session metrics — deploy \"{deploy}\" "
        f"({summary['total']} VMs)[/bold]\n"
    )

    console.print("[bold]Funnel[/bold]")
    total = summary["total"] or 1
    for stage, count in summary["funnel"].items():
        pct = round(count / total * 100)
        bar = "█" * (pct // 5)
        console.print(
            f"  {stage:<8} {count:>3} / {summary['total']:<3} {pct:>3}%  {bar}"
        )

    label = _subject_label(cfg)
    console.print("\n[bold]Summary[/bold]")
    t = Table(show_header=False, box=None)
    t.add_row(f"Median time in {label}", _fmt_hms(summary["median_subject"]))
    t.add_row("Median time-to-first-train", _fmt_hms(summary["median_train"]))
    t.add_row(
        "Median labeled frames",
        str(summary["median_frames"]) if summary["median_frames"] is not None else "—",
    )
    t.add_row(
        "Median epochs completed",
        str(summary["median_epochs"]) if summary["median_epochs"] is not None else "—",
    )
    console.print(t)
