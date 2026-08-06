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

    Two flags, at most one of which is set, because they have different
    fixes and so must produce different advice:

    ``is_auth``
        Authentication — we cannot establish who the caller is (absent,
        expired, or invalid credentials). Fixed by supplying credentials.
    ``is_permission``
        Authorization — the caller is known, but not allowed to make this
        call. Fixed by an IAM policy change; re-authenticating with the
        same identity changes nothing.

    Neither set means something else went wrong (throttling, endpoint
    trouble) and the error is reported verbatim with no advice, since
    telling someone to run 'aws configure' over a throttling error just
    wastes their time.
    """

    def __init__(
        self,
        message: str,
        *,
        is_auth: bool = False,
        is_permission: bool = False,
    ) -> None:
        super().__init__(message)
        self.is_auth = is_auth
        self.is_permission = is_permission


# "We cannot establish who you are" — the fix is new/refreshed credentials.
_AUTHENTICATION_ERROR_CODES = frozenset({
    "AuthFailure",
    "ExpiredToken",
    "ExpiredTokenException",
    "InvalidClientTokenId",
    "RequestExpired",
    "SignatureDoesNotMatch",
    "UnrecognizedClientException",
})

# "We know who you are, and you may not do this" — the fix is an IAM
# policy change. Kept separate from the codes above because the credential
# remedies cannot resolve these, and offering them sends the operator in
# circles re-authenticating an identity that was never the problem.
_AUTHORIZATION_ERROR_CODES = frozenset({
    "AccessDenied",
    "AccessDeniedException",
    "UnauthorizedOperation",
})

# Printed one per line: Rich wraps at the console width, and a hint
# folded mid-command is a hint the operator can't copy-paste.
AWS_CREDENTIALS_REMEDIES = (
    "aws configure",
    "export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=...",
    "aws sso login   (if this account uses SSO)",
)

# Deliberately does not name the credential commands, even to dismiss
# them — a skimming operator would try them anyway.
AWS_PERMISSION_REMEDY_LINES = (
    "These credentials are valid but lack permission for this call.",
    "Grant the calling identity the action named above (for example",
    "ec2:DescribeInstances), or switch to a role or profile that has it.",
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
        if code in _AUTHORIZATION_ERROR_CODES:
            return AwsQueryError(
                f"AWS denied the request: {code} — {msg}",
                is_permission=True,
            )
        if code in _AUTHENTICATION_ERROR_CODES:
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
    """Print an AwsQueryError with advice matching the kind of failure."""
    label = f"[red]{prefix}:[/red] " if prefix else "[red]✗[/red] "
    console.print(f"  {label}{err}")
    if err.is_auth:
        console.print("  [dim]Authenticate with one of:[/dim]")
        for remedy in AWS_CREDENTIALS_REMEDIES:
            console.print(f"    [dim]{remedy}[/dim]")
    elif err.is_permission:
        for line in AWS_PERMISSION_REMEDY_LINES:
            console.print(f"  [dim]{line}[/dim]")


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
    """Determine the allocator base URL from terraform outputs or config.

    Manual provider has neither input: no Terraform state to read an IP
    from, and ``dns.enabled`` is meaningless for a compose stack. Both
    compose templates publish ``${HTTP_PORT}:5000`` on the host, and the
    CLI's manual paths already assume they run on that host (`status` and
    `logs` shell into the local container), so localhost is the address —
    the same base URL deploy_compose._health_poll polls after `up`.
    Imported lazily: deploy_compose imports this module at load time.
    """
    if getattr(cfg, "provider", "aws") == "manual":
        from lablink_cli.commands.deploy_compose import DEFAULT_HTTP_PORT

        return f"http://localhost:{DEFAULT_HTTP_PORT}"

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

# Manual provider keeps its deploy-time copy somewhere else entirely (the
# rendered compose dir, no environment scoping), so the AWS wording above
# would send a BYO operator to a path that does not exist on their machine.
MANUAL_ADMIN_CREDENTIALS_HINT_LINES = (
    "Check app.admin_user / app.admin_password in your config, or in",
    "~/.lablink/compose/<deployment>/config.yaml",
    "(rendered at deploy time — a redeploy can change them).",
)


def print_admin_credentials_hint(cfg: Config | None = None) -> None:
    """Print where admin credentials come from, after a rejected login.

    ``cfg`` selects which deploy-time file to name; omit it (or pass a
    non-manual config) for the AWS deploy dir.
    """
    manual = cfg is not None and getattr(cfg, "provider", "aws") == "manual"
    lines = (
        MANUAL_ADMIN_CREDENTIALS_HINT_LINES
        if manual
        else ADMIN_CREDENTIALS_HINT_LINES
    )
    for line in lines:
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


def resolve_from_saved_config(path: Path) -> tuple[str, str] | None:
    """Try to get credentials from a deploy-time config.yaml at ``path``.

    Both providers stash the resolved credentials in a rendered config.yaml,
    just in different places (AWS: the deploy dir, manual: the compose
    workdir), so the read is shared and only the path differs.
    """
    import yaml

    if not path.exists():
        return None

    with open(path) as f:
        saved_cfg = yaml.safe_load(f) or {}

    app_cfg = saved_cfg.get("app", {}) or {}
    user = app_cfg.get("admin_user", "")
    pw = app_cfg.get("admin_password", "")

    if user and user not in _MISSING and pw and pw not in _MISSING:
        return user, pw
    return None


def _resolve_from_deploy_dir(
    cfg: Config,
) -> tuple[str, str] | None:
    """Try to get credentials from the AWS deployment config."""
    return resolve_from_saved_config(
        get_deploy_dir(cfg) / "config" / "config.yaml"
    )


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
    2. Deployment-specific config written during deploy — the AWS deploy
       dir, or the rendered compose workdir under the manual provider
       (which has no deploy dir at all, so the AWS lookup always missed
       and every BYO operator got prompted)
    3. Interactive prompt (last resort)

    Returns ``(admin_user, admin_password)``.
    """
    resolved = _resolve_from_config(cfg)
    if resolved:
        return resolved

    if getattr(cfg, "provider", "aws") == "manual":
        # Lazy: deploy_compose imports this module at load time.
        from lablink_cli.commands.deploy_compose import compose_workdir

        resolved = resolve_from_saved_config(
            compose_workdir(cfg) / "config.yaml"
        )
    else:
        resolved = _resolve_from_deploy_dir(cfg)

    return resolved or _resolve_from_prompt()
