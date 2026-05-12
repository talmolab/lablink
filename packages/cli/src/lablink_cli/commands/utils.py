"""Shared helpers for CLI commands."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from rich.console import Console

from lablink_allocator_service.conf.structured_config import Config

console = Console()


# ------------------------------------------------------------------
# EC2 instance helpers
# ------------------------------------------------------------------
def _parse_instances(resp: dict) -> list[dict]:
    """Extract VM info dicts from an EC2 describe_instances response."""
    vms = []
    for reservation in resp.get("Reservations", []):
        for inst in reservation.get("Instances", []):
            name = ""
            for tag in inst.get("Tags", []):
                if tag["Key"] == "Name":
                    name = tag["Value"]
                    break
            vms.append(
                {
                    "name": name,
                    "instance_id": inst["InstanceId"],
                    "type": inst["InstanceType"],
                    "state": inst["State"]["Name"],
                    "launch_time": inst.get("LaunchTime", ""),
                    "public_ip": inst.get("PublicIpAddress", "—"),
                }
            )
    return vms


def query_ec2_instances(
    region: str,
    tag_pattern: str,
    states: list[str] | None = None,
) -> list[dict]:
    """Query EC2 instances by Name tag pattern and state.

    Args:
        region: AWS region.
        tag_pattern: Glob pattern for the Name tag (e.g. ``"my-app-*"``).
        states: Instance states to match. Defaults to ``["running"]``.

    Returns:
        List of VM info dicts.
    """
    from lablink_cli.commands.setup import _get_session

    if states is None:
        states = ["running"]

    try:
        session = _get_session(region)
        ec2 = session.client("ec2")
    except Exception:
        return []

    try:
        resp = ec2.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [tag_pattern]},
                {"Name": "instance-state-name", "Values": states},
            ]
        )
    except Exception:
        return []

    return _parse_instances(resp)


def get_allocator_vm(cfg: Config) -> dict | None:
    """Find the allocator EC2 instance for this deployment."""
    tag = f"{cfg.deployment_name}-allocator-{cfg.environment}"
    vms = query_ec2_instances(cfg.app.region, tag)
    if vms:
        vms[0]["vm_type"] = "allocator"
        return vms[0]
    return None


def get_client_vms(cfg: Config) -> list[dict]:
    """Query EC2 for LabLink client VMs."""
    tag = (
        f"{cfg.machine.software}-lablink-client-"
        f"{cfg.environment}-vm-*"
    )
    vms = query_ec2_instances(
        cfg.app.region,
        tag,
        states=["running", "stopped", "pending"],
    )
    for vm in vms:
        vm["vm_type"] = "client"
    return vms


def list_all_vms(cfg: Config) -> list[dict]:
    """Return allocator + client VMs for this deployment."""
    vms: list[dict] = []
    allocator = get_allocator_vm(cfg)
    if allocator:
        vms.append(allocator)
    vms.extend(get_client_vms(cfg))
    return vms


def get_terraform_outputs(deploy_dir: Path) -> dict[str, str]:
    """Read terraform outputs as a dict."""
    try:
        result = subprocess.run(
            ["terraform", "output", "-json"],
            cwd=deploy_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        raw = json.loads(result.stdout)
        return {
            k: v.get("value", "")
            for k, v in raw.items()
        }
    except (subprocess.CalledProcessError, json.JSONDecodeError):
        return {}


def get_deploy_dir(cfg: Config) -> Path:
    """Return the scoped deploy directory for this deployment."""
    return (
        Path.home()
        / ".lablink"
        / "deploy"
        / cfg.deployment_name
        / cfg.environment
    )


def get_allocator_url(cfg: Config) -> str:
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


_MISSING = ("MISSING", "")


def _resolve_from_config(
    cfg: Config,
) -> tuple[str, str] | None:
    """Try to get credentials from the main config."""
    user = cfg.app.admin_user
    pw = cfg.app.admin_password
    if user not in _MISSING and pw not in _MISSING:
        return user, pw
    return None


def _resolve_from_deploy_dir(
    cfg: Config,
) -> tuple[str, str] | None:
    """Try to get credentials from the deployment config."""
    import yaml

    deploy_config_path = (
        get_deploy_dir(cfg) / "config" / "config.yaml"
    )
    if not deploy_config_path.exists():
        return None

    with open(deploy_config_path) as f:
        deploy_cfg = yaml.safe_load(f) or {}

    app_cfg = deploy_cfg.get("app", {})
    user = app_cfg.get("admin_user", "")
    pw = app_cfg.get("admin_password", "")

    if user and user not in _MISSING and pw and pw not in _MISSING:
        return user, pw
    return None


def _resolve_from_prompt() -> tuple[str, str]:
    """Prompt the user for admin credentials."""
    import getpass

    admin_user = (
        input("  Admin username [admin]: ").strip()
        or "admin"
    )
    admin_pw = getpass.getpass("  Admin password: ")
    if not admin_pw:
        console.print(
            "  [red]Admin password is required[/red]"
        )
        raise SystemExit(1)
    console.print()
    return admin_user, admin_pw


def resolve_admin_credentials(
    cfg: Config,
) -> tuple[str, str]:
    """Resolve admin credentials from config, deployment dir, or prompt.

    Resolution order:
    1. Main config (``cfg.app.admin_user`` / ``cfg.app.admin_password``)
    2. Deployment-specific config saved during deploy
    3. Interactive prompt (last resort)

    Returns ``(admin_user, admin_password)``.
    """
    return (
        _resolve_from_config(cfg)
        or _resolve_from_deploy_dir(cfg)
        or _resolve_from_prompt()
    )
