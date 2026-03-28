"""Shared helpers for CLI commands."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from lablink_allocator_service.conf.structured_config import Config

console = Console()


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
    from lablink_cli.commands.status import get_terraform_outputs

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
    import getpass

    import yaml

    admin_user = cfg.app.admin_user
    admin_pw = cfg.app.admin_password

    deploy_config_path = (
        get_deploy_dir(cfg) / "config" / "config.yaml"
    )
    if (
        admin_user in ("MISSING", "")
        or admin_pw in ("MISSING", "")
    ) and deploy_config_path.exists():
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

    return admin_user, admin_pw
