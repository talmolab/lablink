"""Export VM metrics from the allocator to a CSV file."""

from __future__ import annotations

import base64
import csv
import json
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rich.console import Console

from lablink_cli.commands.utils import (
    get_allocator_url,
    resolve_admin_credentials,
)

console = Console()


VALID_FORMATS = ("csv", "json")


def run_export_metrics(
    cfg,
    output: str | None = None,
    include_logs: bool = False,
    format: str = "csv",
) -> None:
    """Export VM metrics from the allocator to a file.

    Args:
        cfg: LabLink configuration object.
        output: Path for the output file. If None, defaults to
            ``metrics.<format>`` in the current directory.
        include_logs: Whether to include cloud_init and docker log columns.
        format: Output format, one of "csv" or "json".
    """
    if format not in VALID_FORMATS:
        console.print(
            f"[red]Invalid format '{format}'. Must be one of: "
            f"{', '.join(VALID_FORMATS)}[/red]"
        )
        raise SystemExit(1)

    if output is None:
        output = f"metrics.{format}"

    allocator_url = get_allocator_url(cfg)
    if not allocator_url:
        console.print("[red]Could not determine allocator URL.[/red]")
        raise SystemExit(1)

    admin_user, admin_pw = resolve_admin_credentials(cfg)

    logs_param = "true" if include_logs else "false"
    url = f"{allocator_url}/api/export-metrics?include_logs={logs_param}"

    credentials = base64.b64encode(
        f"{admin_user}:{admin_pw}".encode()
    ).decode()

    req = Request(url, method="GET")
    req.add_header("Authorization", f"Basic {credentials}")
    req.add_header("Accept", "application/json")

    ctx = ssl.create_default_context()
    if cfg.ssl.provider == "self_signed":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    try:
        resp = urlopen(req, timeout=60, context=ctx)
        body = json.loads(resp.read().decode())
    except HTTPError as e:
        console.print(f"[red]HTTP {e.code}: {e.reason}[/red]")
        raise SystemExit(1) from e
    except URLError as e:
        console.print(f"[red]Connection error: {e.reason}[/red]")
        raise SystemExit(1) from e
    except json.JSONDecodeError as e:
        console.print(
            f"[red]Invalid JSON response from allocator: {e}[/red]"
        )
        raise SystemExit(1) from e

    vms = body.get("vms", [])
    if not vms:
        console.print("[yellow]No VMs found to export.[/yellow]")
        return

    output_path = Path(output)

    if format == "json":
        with open(output_path, "w") as f:
            json.dump(vms, f, indent=2)
    else:
        fieldnames = list(vms[0].keys())
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(vms)

    console.print(
        f"[green]Exported {len(vms)} VMs to {output_path}[/green]"
    )
