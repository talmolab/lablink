"""Launch client VMs via the allocator service."""

from __future__ import annotations

import base64
import getpass
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from rich.console import Console

from lablink_allocator_service.conf.structured_config import Config

from lablink_cli.commands.deploy import get_deploy_dir
from lablink_cli.commands.status import get_terraform_outputs

console = Console()


def _get_allocator_url(cfg: Config) -> str:
    """Determine the allocator base URL from terraform outputs or config."""
    deploy_dir = get_deploy_dir(cfg)
    outputs = {}
    if deploy_dir.exists():
        outputs = get_terraform_outputs(deploy_dir)

    ip = outputs.get("ec2_public_ip", "")
    domain = cfg.dns.domain if cfg.dns.enabled else ""
    use_https = cfg.ssl.provider != "none"

    if domain and use_https:
        return f"https://{domain}"
    elif domain:
        return f"http://{domain}"
    elif ip:
        return f"http://{ip}"
    return ""


def run_launch(cfg: Config, num_vms: int) -> None:
    """Launch client VMs by calling the allocator /api/launch endpoint."""
    console.print()

    # Resolve allocator URL
    allocator_url = _get_allocator_url(cfg)
    if not allocator_url:
        console.print(
            "[red]Could not determine allocator URL.[/red]\n"
            "Run 'lablink deploy' first or check 'lablink status'."
        )
        raise SystemExit(1)

    # Read admin credentials — try deployment config first,
    # then fall back to ~/.lablink/config.yaml, then prompt.
    admin_user = cfg.app.admin_user
    admin_pw = cfg.app.admin_password

    deploy_dir = get_deploy_dir(cfg)
    deploy_config_path = deploy_dir / "config" / "config.yaml"
    if (
        admin_user in ("MISSING", "")
        or admin_pw in ("MISSING", "")
    ) and deploy_config_path.exists():
        import yaml

        with open(deploy_config_path) as f:
            deploy_cfg = yaml.safe_load(f) or {}
        app_cfg = deploy_cfg.get("app", {})
        if admin_user in ("MISSING", ""):
            admin_user = app_cfg.get("admin_user", "")
        if admin_pw in ("MISSING", ""):
            admin_pw = app_cfg.get("admin_password", "")

    if admin_user in ("MISSING", ""):
        admin_user = (
            input("  Admin username [admin]: ").strip()
            or "admin"
        )
    if admin_pw in ("MISSING", ""):
        admin_pw = getpass.getpass("  Admin password: ")
        if not admin_pw:
            console.print(
                "  [red]Admin password is required[/red]"
            )
            raise SystemExit(1)
        console.print()

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
