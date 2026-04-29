"""`lablink login` — orchestrate Identity Center bootstrap + SSO sign-in."""

from __future__ import annotations

import configparser
import datetime as dt
import json
import webbrowser

import boto3
import typer
from rich.console import Console
from rich.panel import Panel

from lablink_cli.auth import policy
from lablink_cli.auth.bootstrap import (
    CREATE_PERMISSION_SET_URL,
    SSOBootstrapResult,
    copy_to_clipboard,
    run_bootstrap,
)
from lablink_cli.auth.credentials import (
    PROFILE_NAME,
    SSO_SESSION_NAME,
    has_sso_profile,
    is_logged_in,
)
from lablink_cli.auth.sso_flow import (
    SSOConfig,
    login as sso_login,
    resolve_role,
    select_account,
)
from lablink_cli.auth.utils import aws_config_path, sso_cache_path

console = Console()


def _read_sso_config() -> SSOConfig:
    parser = configparser.ConfigParser()
    parser.read(aws_config_path())
    section = f"sso-session {SSO_SESSION_NAME}"
    return SSOConfig(
        start_url=parser.get(section, "sso_start_url"),
        region=parser.get(section, "sso_region"),
    )


def _read_profile_field(field: str) -> str | None:
    parser = configparser.ConfigParser()
    parser.read(aws_config_path())
    section = f"profile {PROFILE_NAME}"
    if section not in parser.sections():
        return None
    return parser.get(section, field, fallback=None)


def _write_profile_field(field: str, value: str) -> None:
    cfg_path = aws_config_path()
    parser = configparser.ConfigParser()
    parser.read(cfg_path)
    section = f"profile {PROFILE_NAME}"
    if section not in parser.sections():
        parser.add_section(section)
    parser.set(section, field, value)
    with open(cfg_path, "w") as fp:
        parser.write(fp)


def _token_expiry_human() -> str:
    """Return a human-readable 'in 4h 12m' for the cached SSO token."""
    cache_path = sso_cache_path(SSO_SESSION_NAME)

    try:
        data = json.loads(cache_path.read_text())
        expiry = dt.datetime.fromisoformat(
            data["expiresAt"].replace("Z", "+00:00")
        )
    except (OSError, KeyError, ValueError):
        return "unknown"

    delta = expiry - dt.datetime.now(dt.timezone.utc)
    seconds = max(0, int(delta.total_seconds()))
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    return f"{hours}h {minutes}m"


def run_steady_state() -> None:
    """Run the SSO device-code flow against the existing [sso-session lablink]."""
    sso_config = _read_sso_config()

    access_token = sso_login(sso_config)

    account_id = _read_profile_field("sso_account_id")
    if not account_id:
        account_id = select_account(
            sso_config=sso_config, access_token=access_token
        )
        _write_profile_field("sso_account_id", account_id)

    role = _read_profile_field("sso_role_name") or "lablink"
    resolved_role = resolve_role(
        sso_config=sso_config,
        access_token=access_token,
        account_id=account_id,
        preferred_role_name=role,
    )
    if resolved_role != role:
        _write_profile_field("sso_role_name", resolved_role)

    sts = boto3.Session(profile_name=PROFILE_NAME).client("sts")
    identity = sts.get_caller_identity()
    expiry_human = _token_expiry_human()

    console.print(
        "\n[green]✓[/green] Signed in via Identity Center"
    )
    console.print(f"[green]✓[/green] AWS Account: [bold]{account_id}[/bold]")
    console.print(f"[green]✓[/green] Permission set: [bold]{resolved_role}[/bold]")
    console.print(f"[green]✓[/green] Token valid for: [bold]{expiry_human}[/bold]")
    console.print(f"[dim]ARN: {identity.get('Arn', '')}[/dim]\n")


def run_login(
    deployment_region: str | None = None,
    update_policy: bool = False,
) -> None:
    """Top-level login orchestrator."""
    if update_policy:
        payload = policy.render_inline_policy_json()
        copy_to_clipboard(payload)
        console.print(
            Panel(
                "Permission set policy JSON copied to your clipboard.\n\n"
                "Open the AWS Console, navigate to your [bold]lablink[/bold]\n"
                "permission set, and replace its inline policy with the\n"
                "clipboard contents.",
                title="Update policy",
                border_style="cyan",
            )
        )
        webbrowser.open(CREATE_PERMISSION_SET_URL)
        return

    if is_logged_in():
        expiry = _token_expiry_human()
        console.print(
            f"Already signed in, valid for [bold]{expiry}[/bold]."
        )
        if not typer.confirm("Re-login?", default=False):
            return

    if not has_sso_profile():
        result: SSOBootstrapResult = run_bootstrap(
            deployment_region=deployment_region or "us-east-1"
        )
        console.print(
            f"\n[green]✓[/green] Identity Center configured "
            f"({result.start_url})\n"
        )

    run_steady_state()
