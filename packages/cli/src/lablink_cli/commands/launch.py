"""Launch client VMs via the allocator service."""

from __future__ import annotations

import re
import time

from rich.console import Console

from lablink_allocator_service.conf.structured_config import Config

from lablink_cli.api import (
    AllocatorAPI,
    AllocatorAuthError,
    AllocatorError,
    AllocatorUnavailableError,
)
from lablink_cli.commands.utils import (
    get_allocator_url,
    resolve_admin_credentials,
)

console = Console()


# Matches `Apply complete! Resources: N added, N changed, N destroyed.`
_APPLY_SUMMARY_RE = re.compile(
    r"Apply complete!\s+Resources:\s+"
    r"(\d+)\s+added,\s+(\d+)\s+changed,\s+(\d+)\s+destroyed",
)


def _summarize_apply(output: str) -> str | None:
    """Extract the resource-counts line from `terraform apply` output.
    Returns None if the line is missing (older Terraform, partial run, etc.)."""
    m = _APPLY_SUMMARY_RE.search(output)
    if not m:
        return None
    added, changed, destroyed = m.groups()
    return f"Resources: {added} added, {changed} changed, {destroyed} destroyed"


def _format_duration(seconds: float) -> str:
    """Render a duration as `1m 23s` or `45s`."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    mins, secs = divmod(seconds, 60)
    return f"{mins}m {secs}s"


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

    started = time.monotonic()
    try:
        with console.status(
            f"[bold]Launching {num_vms} client VM(s)...[/bold]",
            spinner="dots",
        ):
            result = api.launch_vms(num_vms)
        elapsed = time.monotonic() - started

        output = (result or {}).get("output", "")
        summary = _summarize_apply(output)
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
