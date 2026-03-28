"""Launch client VMs via the allocator service."""

from __future__ import annotations

import base64
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from rich.console import Console

from lablink_allocator_service.conf.structured_config import Config

from lablink_cli.commands.utils import (
    get_allocator_url,
    resolve_admin_credentials,
)

console = Console()


def run_launch(cfg: Config, num_vms: int) -> None:
    """Launch client VMs by calling the allocator /api/launch endpoint."""
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
    req.add_header("Authorization", f"Basic {credentials}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")

    console.print(
        f"[bold]Launching {num_vms} client VM(s)...[/bold]"
    )
    console.print(f"  [dim]POST {url}[/dim]")
    console.print()

    # SSL context — handle self-signed certs
    ctx = ssl.create_default_context()
    if cfg.ssl.provider == "self_signed":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    try:
        resp = urlopen(req, timeout=600, context=ctx)  # noqa: S310
        body = json.loads(resp.read().decode())

        if body.get("status") == "success":
            console.print("[green]Launch successful![/green]")
            output = body.get("output", "")
            if output:
                console.print()
                console.print("[bold]Terraform output:[/bold]")
                console.print(output)
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
