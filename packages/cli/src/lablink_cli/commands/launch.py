"""Launch and destroy client VMs via the allocator service."""

from __future__ import annotations

import time
from typing import Callable, NoReturn

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
    format_duration,
    get_allocator_url,
    resolve_admin_credentials,
    summarize_terraform,
)

console = Console()


def _resolve_api(cfg: Config) -> tuple[AllocatorAPI, str]:
    """Build an allocator client from config, prompting for credentials if
    they were never saved.

    Returns ``(api, allocator_url)``; exits 1 if the deployment's URL
    cannot be determined.
    """
    allocator_url = get_allocator_url(cfg)
    if not allocator_url:
        console.print(
            "[red]Could not determine allocator URL.[/red]\n"
            "Run 'lablink deploy' first or check 'lablink status'."
        )
        raise SystemExit(1)

    admin_user, admin_pw = resolve_admin_credentials(cfg)
    api = AllocatorAPI(allocator_url, admin_user, admin_pw, cfg.ssl.provider)
    return api, allocator_url


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
    propagate untouched — callers map them via ``_exit_fleet_error``.
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


def _report(
    result: dict | None,
    elapsed: float,
    *,
    label: str,
    verbose: bool,
) -> None:
    """Print the success line and Terraform's resource summary, plus the
    raw Terraform output under ``verbose``."""
    output = (result or {}).get("output", "")
    console.print(
        f"[green]✓ {label}[/green]  [dim]({format_duration(elapsed)})[/dim]"
    )
    summary = summarize_terraform(output)
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


def _exit_fleet_error(e: AllocatorError, *, label: str) -> NoReturn:
    """Report a failed fleet operation and exit 1.

    Auth and connectivity failures get their own advice because the fix
    differs. Everything else (409 already-in-progress, 405 unsupported,
    poll timeout, HTTP 5xx) is reported verbatim under ``label`` — the
    allocator's own message is more specific than anything we'd invent.
    """
    if isinstance(e, AllocatorAuthError):
        console.print(
            "[red]Authentication failed.[/red] Check your admin credentials."
        )
    elif isinstance(e, AllocatorUnavailableError):
        console.print(f"[red]Could not connect to allocator:[/red] {e}")
        console.print(
            "  Check that the allocator is running with 'lablink status'."
        )
    else:
        console.print(f"[red]{label}:[/red] {e}")
    raise SystemExit(1)


def run_launch(cfg: Config, num_vms: int, *, verbose: bool = False) -> None:
    """Launch client VMs by calling the allocator /api/launch endpoint."""
    if cfg.provider == "manual":
        console.print(
            "Manual provider has no VMs to launch — each BYO box "
            "runs `lablink client register` to join the pool. See "
            "`lablink status` for currently registered clients."
        )
        return

    console.print()
    api, allocator_url = _resolve_api(cfg)

    console.print(f"  [dim]POST {allocator_url}/api/launch[/dim]")
    console.print()

    try:
        result, elapsed = _run_fleet_op(
            lambda on_progress: api.launch_vms(
                num_vms, on_progress=on_progress
            ),
            description=f"[bold]Launching {num_vms} client VM(s)...[/bold]",
        )
        _report(result, elapsed, label="Launch successful", verbose=verbose)
    except AllocatorError as e:
        _exit_fleet_error(e, label="Launch failed")

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
    if cfg.provider == "manual":
        console.print(
            "Manual provider has no VMs to destroy — each BYO box "
            "leaves the pool by running `lablink client unregister` "
            "on that box. See `lablink status` for currently "
            "registered clients."
        )
        return

    console.print()
    api, allocator_url = _resolve_api(cfg)

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

    console.print(f"  [dim]POST {allocator_url}/destroy[/dim]")
    console.print()

    try:
        result, elapsed = _run_fleet_op(
            lambda on_progress: api.destroy_vms(on_progress=on_progress),
            description="[bold]Destroying client VMs...[/bold]",
        )
        _report(result, elapsed, label="client VMs destroyed", verbose=verbose)
    except AllocatorNotFoundError:
        # Nothing was ever launched, so there is nothing to tear down.
        # Not a failure: the command is idempotent. Must precede the
        # AllocatorError clause below — it is a subclass.
        console.print(
            "[yellow]No client VMs were launched — "
            "nothing to destroy.[/yellow]"
        )
        return
    except AllocatorError as e:
        _exit_fleet_error(e, label="Client destroy failed")

    console.print()
    console.print(
        "[dim]Run 'lablink client launch --num-vms N' to refill the "
        "pool.[/dim]"
    )
