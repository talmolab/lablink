"""Launch client VMs via the allocator service."""

from __future__ import annotations

import base64
import json
import re
import ssl
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from rich.console import Console

from lablink_allocator_service.conf.structured_config import Config

from lablink_cli.api import USER_AGENT
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

    # Resolve allocator URL
    allocator_url = get_allocator_url(cfg)
    if not allocator_url:
        console.print(
            "[red]Could not determine allocator URL.[/red]\n"
            "Run 'lablink deploy' first or check 'lablink status'."
        )
        raise SystemExit(1)

    admin_user, admin_pw = resolve_admin_credentials(cfg)

    # Build request
    url = f"{allocator_url}/api/launch"
    data = urlencode({"num_vms": str(num_vms)}).encode()

    credentials = base64.b64encode(
        f"{admin_user}:{admin_pw}".encode()
    ).decode()

    req = Request(url, data=data, method="POST")
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Authorization", f"Basic {credentials}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")

    console.print(f"  [dim]POST {url}[/dim]")
    console.print()

    # SSL context — handle self-signed certs
    ctx = ssl.create_default_context()
    if cfg.ssl.provider == "self_signed":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    started = time.monotonic()
    try:
        with console.status(
            f"[bold]Launching {num_vms} client VM(s)...[/bold]",
            spinner="dots",
        ):
            resp = urlopen(req, timeout=600, context=ctx)  # noqa: S310
            body = json.loads(resp.read().decode())
        elapsed = time.monotonic() - started

        if body.get("status") == "success":
            output = body.get("output", "")
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
        else:
            console.print(
                f"[yellow]Unexpected response:[/yellow] {body}"
            )

    except HTTPError as e:
        if e.code == 401:
            console.print(
                "[red]Authentication failed.[/red] "
                "Check your admin credentials."
            )
        else:
            # Try to parse JSON error body
            try:
                body = json.loads(e.read().decode())
                error_msg = body.get("error", str(e))
            except (json.JSONDecodeError, UnicodeDecodeError):
                error_msg = str(e)
            console.print(
                f"[red]Launch failed (HTTP {e.code}):[/red] {error_msg}"
            )
        raise SystemExit(1)

    except URLError as e:
        console.print(
            f"[red]Could not connect to allocator:[/red] {e.reason}"
        )
        console.print(
            "  Check that the allocator is running with 'lablink status'."
        )
        raise SystemExit(1)

    console.print()
    console.print(
        "[dim]Run 'lablink status' to see client VMs.[/dim]"
    )
