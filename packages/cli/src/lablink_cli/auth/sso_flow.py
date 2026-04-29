"""SSO login by wrapping the official `aws sso login` command.

We delegate the OIDC device-authorization flow to AWS CLI v2 rather
than implementing it ourselves. AWS CLI is already a documented
prerequisite for LabLink, so requiring it here doesn't add a new
install burden, and the official tool handles edge cases (proxy
config, MFA prompts, browser fallbacks) that we'd otherwise have to
reproduce.

After `aws sso login` finishes, this module reads the access token
that AWS CLI cached at ~/.aws/sso/cache/<sha1>.json and uses it with
boto3 sso clients to discover the user's accounts and permission sets.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass

import boto3
import typer
from rich.console import Console

from lablink_cli.auth import credentials
from lablink_cli.auth.utils import sso_cache_path

console = Console()

AWS_CLI_INSTALL_URL = (
    "https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
)


@dataclass
class SSOConfig:
    start_url: str
    region: str


class AWSCLINotFoundError(credentials.AuthError):
    """AWS CLI v2 is required but not installed."""


class LoginFailedError(credentials.AuthError):
    """`aws sso login` exited non-zero or didn't produce a cached token."""


def _ensure_aws_cli_installed() -> None:
    """Raise AWSCLINotFoundError if `aws` is not on PATH."""
    if shutil.which("aws") is None:
        raise AWSCLINotFoundError(
            "AWS CLI v2 is required for `lablink login`.\n"
            f"Install it from {AWS_CLI_INSTALL_URL}"
        )


def _read_cached_access_token(start_url: str) -> str:
    """Read the SSO access token AWS CLI cached after `aws sso login`."""
    cache_path = sso_cache_path(start_url)
    if not cache_path.exists():
        raise LoginFailedError(
            f"Expected SSO token cache at {cache_path} but it does not exist. "
            "Did `aws sso login` complete successfully?"
        )
    try:
        data = json.loads(cache_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise LoginFailedError(
            f"Could not read SSO token cache at {cache_path}: {e}"
        ) from e
    token = data.get("accessToken")
    if not token:
        raise LoginFailedError(
            f"SSO token cache at {cache_path} has no accessToken field."
        )
    return token


def login(sso_config: SSOConfig) -> str:
    """Run `aws sso login --sso-session lablink` and return the cached token.

    Raises:
        AWSCLINotFoundError: when the `aws` binary is not on PATH.
        LoginFailedError: when `aws sso login` exits non-zero or doesn't
            produce a readable cached token.
    """
    _ensure_aws_cli_installed()

    console.print("\n[dim]Running `aws sso login --sso-session lablink`...[/dim]")
    result = subprocess.run(
        ["aws", "sso", "login", "--sso-session", "lablink"],
        check=False,
    )
    if result.returncode != 0:
        raise LoginFailedError(
            f"`aws sso login` failed with exit code {result.returncode}."
        )

    return _read_cached_access_token(sso_config.start_url)


def select_account(*, sso_config: SSOConfig, access_token: str) -> str:
    """Pick the AWS account to use. Auto-selects when only one is visible."""
    sso = boto3.client("sso", region_name=sso_config.region)
    accounts = sso.list_accounts(accessToken=access_token).get("accountList", [])

    if not accounts:
        raise credentials.AuthError(
            "Your Identity Center user has no AWS accounts assigned. "
            "Did you assign your user to an account during bootstrap?"
        )

    if len(accounts) == 1:
        return accounts[0]["accountId"]

    console.print("\nMultiple AWS accounts available. Choose one:")
    for i, acct in enumerate(accounts, start=1):
        console.print(
            f"  [bold]{i}[/bold]. {acct['accountName']} ({acct['accountId']})"
        )
    while True:
        choice = typer.prompt("Account number")
        try:
            idx = int(choice)
            if 1 <= idx <= len(accounts):
                return accounts[idx - 1]["accountId"]
        except ValueError:
            pass
        console.print("[red]Invalid choice. Try again.[/red]")


def resolve_role(
    *,
    sso_config: SSOConfig,
    access_token: str,
    account_id: str,
    preferred_role_name: str | None = None,
) -> str:
    """Pick the role/permission-set to use within the chosen account."""
    sso = boto3.client("sso", region_name=sso_config.region)
    roles = sso.list_account_roles(
        accessToken=access_token, accountId=account_id
    ).get("roleList", [])

    if not roles:
        raise credentials.AuthError(
            "No permission sets are assigned to your user for this account. "
            "Re-run bootstrap to assign one."
        )

    if preferred_role_name:
        for r in roles:
            if r["roleName"] == preferred_role_name:
                return preferred_role_name

    if len(roles) == 1:
        return roles[0]["roleName"]

    console.print("\nMultiple permission sets available. Choose one:")
    for i, role in enumerate(roles, start=1):
        console.print(f"  [bold]{i}[/bold]. {role['roleName']}")
    while True:
        choice = typer.prompt("Permission set number")
        try:
            idx = int(choice)
            if 1 <= idx <= len(roles):
                return roles[idx - 1]["roleName"]
        except ValueError:
            pass
        console.print("[red]Invalid choice. Try again.[/red]")
