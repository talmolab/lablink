"""Pre-flight checks for LabLink deployment prerequisites."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from lablink_cli.auth.credentials import get_session

console = Console()

DEFAULT_CONFIG = Path.home() / ".lablink" / "config.yaml"

STATUS_STYLES = {
    "pass": "[green]PASS[/green]",
    "fail": "[red]FAIL[/red]",
    "warn": "[yellow]WARN[/yellow]",
}


def _check_terraform() -> dict:
    """Check that terraform is installed and return version."""
    result = {"check": "Terraform installed", "status": "fail"}

    path = shutil.which("terraform")
    if not path:
        result["detail"] = (
            "terraform not found on PATH. "
            "Install from https://developer.hashicorp.com/terraform/install"
        )
        return result

    try:
        proc = subprocess.run(
            ["terraform", "version", "-json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            info = json.loads(proc.stdout)
            version = info.get(
                "terraform_version", "unknown"
            )
            result["status"] = "pass"
            result["detail"] = f"v{version} ({path})"
        else:
            result["status"] = "warn"
            result["detail"] = (
                f"Found at {path} but could not get version"
            )
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        result["status"] = "warn"
        result["detail"] = (
            f"Found at {path} but could not get version"
        )

    return result


def _check_aws_credentials(region: str | None) -> dict:
    """Check AWS credentials are valid.

    Validates inline via sts:GetCallerIdentity rather than calling
    setup.check_credentials, because the latter raises SystemExit on
    failure — which would exit `lablink doctor` instead of continuing
    with the remaining checks.
    """
    result = {"check": "AWS credentials", "status": "fail"}
    try:
        from botocore.exceptions import ClientError

        from lablink_cli.auth.credentials import (
            NotLoggedInError,
            SSOTokenExpiredError,
        )

        try:
            session = get_session(region=region or "us-east-1")
        except NotLoggedInError:
            result["detail"] = (
                "Not signed in. Run [bold]lablink login[/bold] to sign in "
                "via AWS Identity Center."
            )
            return result
        except SSOTokenExpiredError:
            result["detail"] = (
                "SSO session expired. Run [bold]lablink login[/bold] to "
                "refresh."
            )
            return result

        try:
            identity = session.client("sts").get_caller_identity()
        except ClientError as e:
            result["detail"] = (
                f"Credentials present but rejected by STS: {e}. "
                "Run [bold]lablink login[/bold] to refresh."
            )
            return result

        result["status"] = "pass"
        result["detail"] = (
            f"Account: {identity['Account']}, ARN: {identity['Arn']}"
        )
    except Exception as e:
        result["detail"] = f"Unexpected error: {e}"
    return result


def _check_lablink_permissions(region: str | None) -> dict:
    """Audit the live SSO role's permissions against AUDIT_ACTIONS.

    Uses iam:SimulatePrincipalPolicy to dry-run each known lablink action
    and report any denials with a hint to run `lablink login --update-policy`.
    Marked 'warn' (skipped) when the caller isn't on a lablink Identity
    Center role — env-var users haven't opted in to the permission audit.
    """
    from lablink_cli.auth.credentials import (
        NotLoggedInError,
        SSOTokenExpiredError,
    )
    from lablink_cli.auth.policy import AUDIT_ACTIONS

    result = {"check": "LabLink permissions", "status": "fail"}
    try:
        try:
            session = get_session(region=region or "us-east-1")
        except (NotLoggedInError, SSOTokenExpiredError):
            result["status"] = "warn"
            result["detail"] = (
                "Not signed in via Identity Center; skipping permission audit."
            )
            return result

        identity = session.client("sts").get_caller_identity()
        arn = identity.get("Arn", "")
        if "assumed-role" not in arn or "lablink" not in arn.lower():
            result["status"] = "warn"
            result["detail"] = (
                "Not on a lablink Identity Center role; "
                "skipping permission audit."
            )
            return result

        # Convert SSO assumed-role ARN to the underlying IAM role ARN:
        # arn:aws:sts::ACCOUNT:assumed-role/AWSReservedSSO_lablink_HASH/USER
        # → arn:aws:iam::ACCOUNT:role/AWSReservedSSO_lablink_HASH
        principal_arn = (
            arn.replace(":sts:", ":iam:")
            .replace("assumed-role", "role")
            .rsplit("/", 1)[0]
        )

        iam = session.client("iam")
        evaluation = iam.simulate_principal_policy(
            PolicySourceArn=principal_arn,
            ActionNames=AUDIT_ACTIONS,
        )
        denied = [
            r["EvalActionName"]
            for r in evaluation.get("EvaluationResults", [])
            if r.get("EvalDecision") != "allowed"
        ]

        if not denied:
            result["status"] = "pass"
            result["detail"] = (
                f"All {len(AUDIT_ACTIONS)} required actions allowed."
            )
            return result

        result["status"] = "fail"
        result["detail"] = (
            "Permission set is missing actions: "
            + ", ".join(denied)
            + ". Run [bold]lablink login --update-policy[/bold] to refresh."
        )
        return result
    except Exception as e:
        result["status"] = "warn"
        result["detail"] = f"Permission audit unavailable: {e}"
        return result


def _check_config_exists() -> dict:
    """Check that the config file exists."""
    result = {"check": "Config file", "status": "fail"}

    if DEFAULT_CONFIG.exists():
        result["status"] = "pass"
        result["detail"] = str(DEFAULT_CONFIG)
    else:
        result["detail"] = (
            f"{DEFAULT_CONFIG} not found. "
            "Run 'lablink configure' to create one"
        )

    return result


def _check_config_valid() -> tuple[dict, object | None]:
    """Validate the config file. Returns (result, cfg_or_None)."""
    result = {"check": "Config validates", "status": "fail"}

    if not DEFAULT_CONFIG.exists():
        result["status"] = "warn"
        result["detail"] = "Skipped (no config file)"
        return result, None

    try:
        from lablink_cli.config.schema import (
            load_config,
            validate_config,
        )

        cfg = load_config(DEFAULT_CONFIG)
        errors = validate_config(cfg)
        if errors:
            result["status"] = "fail"
            result["detail"] = "; ".join(errors)
        else:
            result["status"] = "pass"
            result["detail"] = "No errors"
        return result, cfg
    except Exception as e:
        result["detail"] = f"Failed to load: {e}"
        return result, None


def _check_s3_bucket(cfg) -> dict:
    """Check that the S3 bucket for Terraform state exists."""
    result = {"check": "S3 state bucket", "status": "fail"}

    if cfg is None:
        result["status"] = "warn"
        result["detail"] = "Skipped (no valid config)"
        return result

    bucket_name = getattr(cfg, "bucket_name", None)
    if not bucket_name:
        result["status"] = "fail"
        result["detail"] = (
            "No bucket_name in config. "
            "Run 'lablink setup' to create one"
        )
        return result

    try:
        session = get_session(region=cfg.app.region)
        s3 = session.client("s3")
        s3.head_bucket(Bucket=bucket_name)
        result["status"] = "pass"
        result["detail"] = bucket_name
    except Exception:
        result["status"] = "fail"
        result["detail"] = (
            f"Bucket '{bucket_name}' not found. "
            "Run 'lablink setup' to recreate it"
        )

    return result


def _check_ami(cfg) -> dict:
    """Check that an AMI is available for the configured region."""
    result = {"check": "AMI for region", "status": "fail"}

    if cfg is None:
        result["status"] = "warn"
        result["detail"] = "Skipped (no valid config)"
        return result

    from lablink_cli.config.schema import AMI_MAP

    region = cfg.app.region
    if region in AMI_MAP:
        result["status"] = "pass"
        result["detail"] = (
            f"{region} → {AMI_MAP[region]}"
        )
    else:
        result["status"] = "fail"
        result["detail"] = (
            f"No AMI defined for region '{region}'. "
            f"Supported: {', '.join(AMI_MAP.keys())}"
        )

    return result


def run_doctor() -> None:
    """Run all pre-flight checks."""
    console.print()
    console.print(
        Panel(
            "[bold]LabLink Doctor[/bold]\n"
            "Checking prerequisites and configuration.",
            border_style="cyan",
        )
    )
    console.print()

    checks: list[dict] = []

    # 1. Terraform
    checks.append(_check_terraform())

    # 2. Config file exists
    checks.append(_check_config_exists())

    # 3. Config validates (also returns the config object)
    valid_result, cfg = _check_config_valid()
    checks.append(valid_result)

    # 4. AWS credentials
    region = cfg.app.region if cfg else None
    checks.append(_check_aws_credentials(region))

    # 5. LabLink permission audit (SSO users only)
    checks.append(_check_lablink_permissions(region))

    # 6. S3 state bucket
    checks.append(_check_s3_bucket(cfg))

    # 7. AMI for region
    checks.append(_check_ami(cfg))

    # Display results
    table = Table(show_header=True)
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")

    all_pass = True
    for c in checks:
        status = c["status"]
        if status != "pass":
            all_pass = False
        table.add_row(
            c["check"],
            STATUS_STYLES.get(status, status),
            c.get("detail", ""),
        )

    console.print(table)
    console.print()

    if all_pass:
        console.print(
            "[green]All checks passed.[/green] "
            "Ready to deploy with 'lablink deploy'."
        )
    else:
        console.print(
            "[yellow]Some checks failed.[/yellow] "
            "Resolve the issues above before deploying."
        )
