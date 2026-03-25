"""Pre-flight checks for LabLink deployment prerequisites."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

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
    """Check AWS credentials are valid."""
    result = {"check": "AWS credentials", "status": "fail"}

    try:
        from lablink_cli.commands.setup import (
            _get_session,
            check_credentials,
        )

        session = _get_session(region or "us-east-1")
        identity = check_credentials(session)
        result["status"] = "pass"
        result["detail"] = (
            f"Account: {identity['account']}, "
            f"Identity: {identity['arn']}"
        )
    except SystemExit:
        result["detail"] = (
            "Invalid or missing. Run 'aws configure' "
            "or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY"
        )
    except Exception as e:
        result["detail"] = str(e)

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

    # 5. AMI for region
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
