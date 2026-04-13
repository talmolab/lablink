"""Export deployment metrics to CSV or JSON.

Two metric sources, selectable via flags:

* ``--client``    : per-VM client metrics fetched from the allocator's
                    ``/api/export-metrics`` endpoint.
* ``--allocator`` : per-deploy allocator metrics from the local CLI cache
                    at ``~/.lablink/deployments/`` (issue #317).

Default (no flag) exports both. ``--allocator`` alone never touches the
network, so it works even after ``lablink destroy``.
"""

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
from lablink_cli.deployment_metrics import load_all_metrics

console = Console()


VALID_FORMATS = ("csv", "json")


def _allocator_sidecar_path(output_path: Path, fmt: str) -> Path:
    """Return the sidecar path next to ``output_path``.

    e.g. ``metrics.csv`` → ``metrics_allocator.csv``.
    """
    return output_path.with_name(f"{output_path.stem}_allocator.{fmt}")


def _export_client_metrics(
    cfg,
    output_path: Path,
    fmt: str,
    include_logs: bool,
) -> None:
    """Fetch per-VM metrics from the allocator and write to ``output_path``."""
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

    if fmt == "json":
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


def _export_allocator_metrics(output_path: Path, fmt: str) -> None:
    """Read CLI-local allocator deployment cache and write to ``output_path``.

    Empty cache → print a yellow notice and skip writing the file (don't
    create a confusing zero-row CSV / empty-list JSON).
    """
    records = load_all_metrics()
    if not records:
        console.print(
            "[yellow]No allocator deployment metrics found in "
            "~/.lablink/deployments/. Run `lablink deploy` first.[/yellow]"
        )
        return

    if fmt == "json":
        with open(output_path, "w") as f:
            json.dump(
                {"allocator_metrics": records, "count": len(records)},
                f,
                indent=2,
            )
    else:  # csv
        # Union of keys across all records → stable header even when records
        # have different optional fields populated (failed vs successful deploys).
        fieldnames: list[str] = []
        seen: set[str] = set()
        for rec in records:
            for k in rec:
                if k not in seen:
                    seen.add(k)
                    fieldnames.append(k)
        with open(output_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)

    console.print(
        f"[green]Exported {len(records)} allocator deployment "
        f"records to {output_path}[/green]"
    )


def run_export_metrics(
    cfg,
    output: str | None = None,
    include_logs: bool = False,
    format: str = "csv",
    client: bool = False,
    allocator: bool = False,
) -> None:
    """Export client and/or allocator metrics.

    Args:
        cfg: LabLink config (only required for ``client=True``; pass ``None``
            when only ``allocator=True``).
        output: Path for the primary output file. When both flags are set,
            this is the client output and the allocator file is written next
            to it with an ``_allocator`` suffix. When only ``allocator=True``,
            this is the allocator file directly.
        include_logs: For client metrics, include cloud_init / docker logs.
        format: ``csv`` or ``json``.
        client: Export per-VM metrics fetched from the allocator.
        allocator: Export per-deploy metrics from the CLI-local cache.

    No flags → both (the common "give me everything" case).
    """
    if format not in VALID_FORMATS:
        console.print(
            f"[red]Invalid format '{format}'. Must be one of: "
            f"{', '.join(VALID_FORMATS)}[/red]"
        )
        raise SystemExit(1)

    # Default: if neither flag is set, export both.
    if not client and not allocator:
        client = True
        allocator = True

    # Resolve output paths. When both sources are exported, --output names
    # the client file and the allocator file is a sidecar. When only the
    # allocator is exported, --output names it directly (no sidecar suffix).
    if client:
        client_path = Path(output) if output else Path(f"metrics.{format}")
    else:
        client_path = None

    if allocator:
        if client:
            assert client_path is not None  # for type narrowing
            allocator_path = _allocator_sidecar_path(client_path, format)
        else:
            allocator_path = (
                Path(output) if output else Path(f"metrics_allocator.{format}")
            )
    else:
        allocator_path = None

    if client:
        assert client_path is not None
        _export_client_metrics(cfg, client_path, format, include_logs)

    if allocator:
        assert allocator_path is not None
        _export_allocator_metrics(allocator_path, format)
