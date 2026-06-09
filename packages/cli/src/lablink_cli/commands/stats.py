"""Render a cohort session-metrics summary in the terminal.

Numbers come from the allocator's /api/session-metrics/summary endpoint —
the same view model the admin web UI consumes. This keeps `lablink stats`
and /admin/session-metrics from ever showing different aggregates for
the same deployment state.
"""

from __future__ import annotations

import base64
import json
import ssl
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
        f"{allocator_url}/api/session-metrics/summary", method="GET"
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


def _fmt_hms(seconds: int | float | None) -> str:
    if seconds is None:
        return "—"
    s = int(seconds)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def run_stats(cfg) -> None:
    body = _fetch(cfg)

    if not body.get("enabled", False):
        console.print(
            "[yellow]Session metrics collection is disabled for this "
            "deployment. Set monitoring.enabled: true in lablink.yaml "
            "to enable.[/yellow]"
        )
        return

    summary = body.get("summary") or {}
    label = body.get("subject_software_label") or "subject"
    total = summary.get("total_vms", 0)

    if total == 0:
        console.print(
            "[yellow]No session metrics yet. Either no VMs have "
            "reported, or monitoring just started.[/yellow]"
        )
        return

    deploy = getattr(cfg, "deployment_name", "lablink")
    console.print(
        f"\n[bold]LabLink session metrics — deploy \"{deploy}\" "
        f"({total} VMs)[/bold]\n"
    )

    console.print("[bold]Funnel[/bold]")
    funnel = summary.get("funnel", {})
    funnel_total = total or 1
    for stage_key, stage_label in (
        ("started", "Started"),
        ("labeled", "Labeled"),
        ("trained", "Trained"),
        ("tracked", "Tracked"),
    ):
        count = funnel.get(stage_key, 0)
        pct = round(count / funnel_total * 100)
        bar = "█" * (pct // 5)
        console.print(
            f"  {stage_label:<8} {count:>3} / {total:<3} {pct:>3}%  {bar}"
        )

    console.print("\n[bold]Summary[/bold]")
    t = Table(show_header=False, box=None)
    t.add_row(
        "% reached training",
        f"{summary.get('pct_reached_training', 0.0):.1f}%",
    )
    t.add_row(
        f"Median time in {label}",
        _fmt_hms(summary.get("median_seconds_in_subject_software")),
    )
    t.add_row(
        "Median time-to-first-train",
        _fmt_hms(summary.get("median_seconds_to_first_train")),
    )
    frames = summary.get("median_labeled_frames")
    t.add_row(
        "Median labeled frames",
        str(frames) if frames is not None else "—",
    )
    epochs = summary.get("median_epochs_completed")
    t.add_row(
        "Median epochs completed",
        str(epochs) if epochs is not None else "—",
    )
    console.print(t)
