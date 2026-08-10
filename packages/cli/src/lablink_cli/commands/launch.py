"""Launch and destroy client VMs via the allocator service."""

from __future__ import annotations

import re
import time
from typing import Callable

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from lablink_allocator_service.conf.structured_config import Config

from lablink_cli.api import (
    AllocatorAPI,
    AllocatorAuthError,
    AllocatorError,
    AllocatorNotFoundError,
    AllocatorUnavailableError,
)
from lablink_cli.commands.utils import (
    get_allocator_url,
    resolve_admin_credentials,
)

console = Console()


# Matches Terraform's `Apply complete!` and `Destroy complete!` summary lines.
_APPLY_SUMMARY_RE = re.compile(
    r"Apply complete!\s+Resources:\s+"
    r"(\d+)\s+added,\s+(\d+)\s+changed,\s+(\d+)\s+destroyed",
)
_DESTROY_SUMMARY_RE = re.compile(
    r"Destroy complete!\s+Resources:\s+(\d+)\s+destroyed",
)


def _summarize_terraform(output: str) -> str | None:
    """Extract Terraform's apply/destroy summary line from raw output.

    Returns None when neither summary matches — a no-op apply, an
    interrupted run, or output captured before the trailing summary.
    """
    m = _APPLY_SUMMARY_RE.search(output)
    if m:
        added, changed, destroyed = m.groups()
        return f"Resources: {added} added, {changed} changed, {destroyed} destroyed"
    m = _DESTROY_SUMMARY_RE.search(output)
    if m:
        (destroyed,) = m.groups()
        return f"Resources: {destroyed} destroyed"
    return None


def _format_duration(seconds: float) -> str:
    """Render a duration as `1m 23s` or `45s`."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    mins, secs = divmod(seconds, 60)
    return f"{mins}m {secs}s"


def _run_fleet_op(
    api_call: Callable[..., dict | None],
    *,
    description: str,
) -> tuple[dict | None, float]:
    """Run a client-fleet operation under a progress bar.

    ``api_call`` is invoked as ``api_call(on_progress=cb)``; the callback
    updates the bar with the allocator's resource counts. The allocator
    reports (None, None) if it predates progress reporting, in which case
    the bar stays indeterminate rather than rendering a literal "None".

    Returns ``(result, elapsed_seconds)``. Exceptions from ``api_call``
    propagate untouched — each caller maps them to its own messages.
    """
    started = time.monotonic()
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(description, total=None)

        def _on_progress(done, total):
            if done is not None and total is not None:
                progress.update(
                    task,
                    completed=done,
                    total=total,
                    description=f"{description} ({done}/{total} resources)",
                )

        result = api_call(on_progress=_on_progress)
    return result, time.monotonic() - started


def run_launch(cfg: Config, num_vms: int, *, verbose: bool = False) -> None:
    """Launch client VMs by calling the allocator /api/launch endpoint."""
    if getattr(cfg, "provider", "aws") == "manual":
        console.print(
            "Manual provider has no VMs to launch — each BYO box "
            "runs `lablink client register` to join the pool. See "
            "`lablink status` for currently registered clients."
        )
        return

    console.print()

    allocator_url = get_allocator_url(cfg)
    if not allocator_url:
        console.print(
            "[red]Could not determine allocator URL.[/red]\n"
            "Run 'lablink deploy' first or check 'lablink status'."
        )
        raise SystemExit(1)

    admin_user, admin_pw = resolve_admin_credentials(cfg)
    api = AllocatorAPI(allocator_url, admin_user, admin_pw, cfg.ssl.provider)

    console.print(f"  [dim]POST {allocator_url}/api/launch[/dim]")
    console.print()

    try:
        result, elapsed = _run_fleet_op(
            lambda on_progress: api.launch_vms(
                num_vms, on_progress=on_progress
            ),
            description=f"[bold]Launching {num_vms} client VM(s)...[/bold]",
        )

        output = (result or {}).get("output", "")
        summary = _summarize_terraform(output)
        console.print(
            f"[green]✓ Launch successful[/green]  "
            f"[dim]({_format_duration(elapsed)})[/dim]"
        )
        if summary:
            console.print(f"  {summary}")
        if verbose and output:
            console.print()
            console.print("[bold]Terraform output:[/bold]")
            console.print(output)
        elif output:
            console.print(
                "  [dim]Pass --verbose to see full Terraform "
                "output.[/dim]"
            )

    except AllocatorAuthError:
        console.print(
            "[red]Authentication failed.[/red] "
            "Check your admin credentials."
        )
        raise SystemExit(1)
    except AllocatorUnavailableError as e:
        console.print(
            f"[red]Could not connect to allocator:[/red] {e}"
        )
        console.print(
            "  Check that the allocator is running with 'lablink status'."
        )
        raise SystemExit(1)
    except AllocatorError as e:
        console.print(
            f"[red]Launch failed:[/red] {e}"
        )
        raise SystemExit(1)

    console.print()
    console.print(
        "[dim]Run 'lablink status' to see client VMs.[/dim]"
    )


def run_client_destroy(
    cfg: Config,
    *,
    yes: bool = False,
    verbose: bool = False,
) -> None:
    """Destroy every client VM by calling the allocator's /destroy endpoint.

    Args:
        cfg: Loaded LabLink config.
        yes: Skip the confirmation prompt.
        verbose: Print the allocator's full Terraform output.
    """
    if getattr(cfg, "provider", "aws") == "manual":
        console.print(
            "Manual provider has no VMs to destroy — each BYO box "
            "leaves the pool by running `lablink client unregister` "
            "on that box. See `lablink status` for currently "
            "registered clients."
        )
        return

    console.print()

    allocator_url = get_allocator_url(cfg)
    if not allocator_url:
        console.print(
            "[red]Could not determine allocator URL.[/red]\n"
            "Run 'lablink deploy' first or check 'lablink status'."
        )
        raise SystemExit(1)

    admin_user, admin_pw = resolve_admin_credentials(cfg)

    if not yes:
        console.print(
            "[bold yellow]This destroys ALL client VMs[/bold yellow] and "
            "clears the allocator's VM table — inventory, per-VM logs, and "
            "session history go with them. Any user connected right now "
            "loses their session."
        )
        console.print(
            "[dim]Export first if you need the numbers: "
            "lablink export-metrics --allocator[/dim]"
        )
        if not typer.confirm("Destroy all client VMs?", default=False):
            console.print("Aborted.")
            return
        console.print()

    api = AllocatorAPI(allocator_url, admin_user, admin_pw, cfg.ssl.provider)

    console.print(f"  [dim]POST {allocator_url}/destroy[/dim]")
    console.print()

    try:
        result, elapsed = _run_fleet_op(
            lambda on_progress: api.destroy_vms(on_progress=on_progress),
            description="[bold]Destroying client VMs...[/bold]",
        )

        output = (result or {}).get("output", "")
        summary = _summarize_terraform(output)
        console.print(
            f"[green]✓ client VMs destroyed[/green]  "
            f"[dim]({_format_duration(elapsed)})[/dim]"
        )
        if summary:
            console.print(f"  {summary}")
        if verbose and output:
            console.print()
            console.print("[bold]Terraform output:[/bold]")
            console.print(output)
        elif output:
            console.print(
                "  [dim]Pass --verbose to see full Terraform output.[/dim]"
            )
    except AllocatorNotFoundError:
        # Nothing was ever launched, so there is nothing to tear down.
        # Not a failure: the command is idempotent.
        console.print(
            "[yellow]No client VMs were launched — "
            "nothing to destroy.[/yellow]"
        )
        return
    except AllocatorAuthError:
        console.print(
            "[red]Authentication failed.[/red] Check your admin credentials."
        )
        raise SystemExit(1)
    except AllocatorUnavailableError as e:
        console.print(f"[red]Could not connect to allocator:[/red] {e}")
        console.print(
            "  Check that the allocator is running with 'lablink status'."
        )
        raise SystemExit(1)
    except AllocatorError as e:
        console.print(f"[red]Client destroy failed:[/red] {e}")
        raise SystemExit(1)

    console.print()
    console.print(
        "[dim]Run 'lablink client launch --num-vms N' to refill the "
        "pool.[/dim]"
    )
