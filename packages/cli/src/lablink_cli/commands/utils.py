"""Shared helpers for CLI commands."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from rich.console import Console

from lablink_allocator_service.conf.structured_config import Config

console = Console()


# ------------------------------------------------------------------
# AWS error reporting
# ------------------------------------------------------------------
class AwsQueryError(Exception):
    """An AWS query could not be answered.

    ``is_auth`` marks the failures an operator fixes by authenticating —
    missing/expired credentials, or an identity without the required IAM
    permission. Those get remediation steps; anything else (throttling,
    endpoint trouble) is reported verbatim, since telling someone to run
    'aws configure' over a throttling error just wastes their time.
    """

    def __init__(self, message: str, *, is_auth: bool = False) -> None:
        super().__init__(message)
        self.is_auth = is_auth


# ClientError codes meaning "who you are is the problem" — both
# unauthenticated (expired/invalid keys) and unauthorized (valid identity,
# missing IAM permission), because the operator's next step is the same
# for both: fix the credentials or the role behind them.
_AUTH_ERROR_CODES = frozenset({
    "AccessDenied",
    "AccessDeniedException",
    "AuthFailure",
    "ExpiredToken",
    "ExpiredTokenException",
    "InvalidClientTokenId",
    "RequestExpired",
    "SignatureDoesNotMatch",
    "UnauthorizedOperation",
    "UnrecognizedClientException",
})

# Printed one per line: Rich wraps at the console width, and a hint
# folded mid-command is a hint the operator can't copy-paste.
AWS_CREDENTIALS_REMEDIES = (
    "aws configure",
    "export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...",
    "aws sso login   (if this account uses SSO)",
)


def _classify_aws_error(e: Exception) -> AwsQueryError:
    """Translate a boto3/botocore exception into an AwsQueryError."""
    from botocore.exceptions import (
        ClientError,
        NoCredentialsError,
        PartialCredentialsError,
        ProfileNotFound,
        SSOTokenLoadError,
        TokenRetrievalError,
        UnauthorizedSSOTokenError,
    )

    if isinstance(e, (NoCredentialsError, PartialCredentialsError)):
        return AwsQueryError(
            f"No usable AWS credentials found ({e})", is_auth=True
        )
    if isinstance(
        e, (TokenRetrievalError, UnauthorizedSSOTokenError, SSOTokenLoadError)
    ):
        return AwsQueryError(
            f"AWS SSO session is not usable ({e})", is_auth=True
        )
    if isinstance(e, ProfileNotFound):
        return AwsQueryError(f"AWS profile not found ({e})", is_auth=True)
    if isinstance(e, ClientError):
        err = (getattr(e, "response", None) or {}).get("Error", {}) or {}
        code = err.get("Code", "") or "Unknown"
        msg = err.get("Message", "") or str(e)
        if code in _AUTH_ERROR_CODES:
            return AwsQueryError(
                f"AWS rejected the request: {code} — {msg}", is_auth=True
            )
        return AwsQueryError(f"AWS API error: {code} — {msg}")
    return AwsQueryError(f"AWS query failed: {e}")


def aws_credentials_error(region: str) -> AwsQueryError | None:
    """Probe STS for the caller identity. Return None if credentials work.

    Deliberately silent, unlike ``setup.check_credentials``, which prints
    a remediation block and raises SystemExit (which is why
    ``doctor._check_aws_credentials`` has to catch SystemExit). Callers
    render their own message so the probe can be used mid-report.
    """
    from lablink_cli.commands.setup import _get_session

    try:
        _get_session(region).client("sts").get_caller_identity()
    except Exception as e:  # boto3 raises many types; classified below
        return _classify_aws_error(e)
    return None


def print_aws_error(err: AwsQueryError, *, prefix: str | None = None) -> None:
    """Print an AwsQueryError, with authentication steps when relevant."""
    label = f"[red]{prefix}:[/red] " if prefix else "[red]✗[/red] "
    console.print(f"  {label}{err}")
    if err.is_auth:
        console.print("  [dim]Authenticate with one of:[/dim]")
        for remedy in AWS_CREDENTIALS_REMEDIES:
            console.print(f"    [dim]{remedy}[/dim]")


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
        List of VM info dicts. Empty only when the query succeeded and
        matched nothing.

    Raises:
        AwsQueryError: the query could not be answered. Callers must not
            report this as "no instances" — that conflation is what made
            ``lablink status`` print an empty inventory when the real
            problem was an unauthenticated caller.
    """
    from lablink_cli.commands.setup import _get_session

    if states is None:
        states = ["running"]

    try:
        ec2 = _get_session(region).client("ec2")
        resp = ec2.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [tag_pattern]},
                {"Name": "instance-state-name", "Values": states},
            ]
        )
    except Exception as e:  # boto3 raises many types; classified below
        raise _classify_aws_error(e) from e

    return _parse_instances(resp)


def get_allocator_vm(cfg: Config) -> dict | None:
    """Find the allocator EC2 instance for this deployment.

    Propagates AwsQueryError from the underlying query — None means the
    instance genuinely isn't there.
    """
    tag = f"{cfg.deployment_name}-allocator-{cfg.environment}"
    vms = query_ec2_instances(cfg.app.region, tag)
    if vms:
        vms[0]["vm_type"] = "allocator"
        return vms[0]
    return None


def get_client_vms(cfg: Config) -> list[dict]:
    """Query EC2 for LabLink client VMs.

    Propagates AwsQueryError — an empty list means no client VMs exist.
    """
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

# The places resolve_admin_credentials draws from, quoted back to the
# operator when the allocator rejects what it produced — a bare "HTTP 401"
# doesn't say which file to go edit. Pre-split into short lines: Rich
# wraps at the console width but does not carry the indent onto
# continuation lines, which looks ragged under an indented bullet.
ADMIN_CREDENTIALS_HINT_LINES = (
    "Check app.admin_user / app.admin_password in your config, or in",
    "~/.lablink/deploy/<deployment>/<environment>/config/config.yaml",
    "(saved at deploy time — a redeploy can change them).",
)


def print_admin_credentials_hint() -> None:
    """Print where admin credentials come from, after a rejected login."""
    for line in ADMIN_CREDENTIALS_HINT_LINES:
        console.print(f"  [dim]{line}[/dim]")


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
