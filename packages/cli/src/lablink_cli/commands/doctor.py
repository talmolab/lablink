"""Pre-flight checks for LabLink deployment prerequisites."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import yaml
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


def _load_config_safe():
    """Load config from default path; return None if missing/invalid.

    On load failure (malformed YAML, permission error, broken structure)
    surfaces a yellow warning so the operator can tell why doctor fell
    through to the AWS prereq path instead of silently doing so.
    """
    if not DEFAULT_CONFIG.exists():
        return None
    try:
        from lablink_cli.config.schema import load_config

        return load_config(DEFAULT_CONFIG)
    except (OSError, yaml.YAMLError, AttributeError, TypeError, ValueError) as e:
        console.print(
            f"[yellow]Could not load {DEFAULT_CONFIG}: {e}.[/yellow]\n"
            "[yellow]Falling back to AWS prereq checks. "
            "Fix the config or run `lablink configure` to regenerate it.[/yellow]"
        )
        return None


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
        from lablink_cli.commands.setup import _get_session

        session = _get_session(cfg.app.region)
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


def _check_aws_prereqs() -> None:
    """Run the AWS-specific pre-flight checks and print a results table."""
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

    # 5. S3 state bucket
    checks.append(_check_s3_bucket(cfg))

    # 6. AMI for region
    checks.append(_check_ami(cfg))

    _render_checks(
        checks,
        pass_message=(
            "[green]All checks passed.[/green] "
            "Ready to deploy with 'lablink deploy'."
        ),
        fail_message=(
            "[yellow]Some checks failed.[/yellow] "
            "Resolve the issues above before deploying."
        ),
    )


def _render_checks(
    checks: list[dict], *, pass_message: str, fail_message: str
) -> bool:
    """Print a check-results table. Returns True if every check passed."""
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
    console.print(pass_message if all_pass else fail_message)
    return all_pass


def _check_manual_prereqs() -> None:
    """Check that docker + docker compose are available (manual provider)."""
    for tool in ("docker",):
        path = shutil.which(tool)
        if path:
            console.print(f"[green]✓[/green] {tool}: {path}")
        else:
            console.print(f"[red]✗[/red] {tool}: not found")

    # docker-compose v2 is a subcommand, not a separate binary
    try:
        result = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            console.print(
                "[green]✓[/green] docker compose: available"
            )
        else:
            console.print(
                "[red]✗[/red] docker compose: missing "
                "(install the Compose plugin)"
            )
    except FileNotFoundError:
        console.print(
            "[red]✗[/red] docker compose: missing "
            "(install the Compose plugin)"
        )


# --------------------------------------------------------------------
# Client-side checks (`lablink client doctor`)
#
# These run ON a registered BYO box, not on the operator's deploy host.
# `lablink doctor` answers "can I deploy from here?"; this answers "is the
# client on this machine actually working?"
# --------------------------------------------------------------------

# A shipper that is alive but hasn't shipped in this long is reporting a
# problem no liveness check can see — the process is up and the container is
# healthy, but nothing is reaching the allocator. That combination went
# unnoticed for a week (lablink#428), which is the reason this command exists.
SHIPPER_STALE_AFTER_S = 15 * 60


def _format_age(seconds: float) -> str:
    """Coarse human age ("6d", "3h", "20m") for the staleness message.

    A raw minute count reads as noise once it passes a few hours
    ("8687 min ago"), and this is the one line an operator scans to decide
    whether logs are flowing.
    """
    if seconds >= 86400:
        return f"{int(seconds // 86400)}d"
    if seconds >= 3600:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 60)}m"


def _check_client_registered() -> dict:
    """Check that `lablink client register` has run on this box."""
    from lablink_cli.commands.register import DEFAULT_ENV_FILE

    result = {"check": "Registered", "status": "fail"}
    if not DEFAULT_ENV_FILE.exists():
        result["detail"] = (
            f"No {DEFAULT_ENV_FILE}. Run `lablink client register` first."
        )
        return result
    result["status"] = "pass"
    result["detail"] = str(DEFAULT_ENV_FILE)
    return result


def _check_client_container() -> dict:
    """Report the lablink-client container's state.

    Doubles as the docker-daemon check: `inspect_container` returns
    "daemon_error" when the daemon is unreachable, so a separate probe would
    only duplicate the same `docker inspect` call.
    """
    from lablink_cli.log_shipper import CONTAINER_NAME, inspect_container

    result = {"check": "Client container", "status": "fail"}
    status = inspect_container(CONTAINER_NAME)

    if status == "daemon_error":
        result["detail"] = (
            "Docker daemon unreachable. Start Docker and re-check."
        )
    elif status == "missing":
        result["detail"] = (
            f"No container named {CONTAINER_NAME}. "
            "Re-run `lablink client register --force` to recreate it."
        )
    elif status == "exited":
        result["detail"] = (
            f"{CONTAINER_NAME} is stopped. "
            "Run `lablink client register` to restart it."
        )
    elif status == "restarting":
        result["status"] = "warn"
        result["detail"] = (
            f"{CONTAINER_NAME} is restarting — it may be crash-looping. "
            f"Check `docker logs {CONTAINER_NAME}`."
        )
    else:
        result["status"] = "pass"
        result["detail"] = f"{CONTAINER_NAME} is running"
    return result


def _check_log_shipper(now: float | None = None) -> dict:
    """Check the log shipper is alive AND actually shipping.

    Liveness alone is not enough. A shipper can sit blocked on a quiet
    container with a full buffer, process up, nothing delivered — so this
    also reports how long ago a batch last landed.
    """
    import time
    from datetime import datetime, timezone

    from lablink_cli.commands.register import _shipper_alive
    from lablink_cli.log_shipper import STATE_FILE, read_last_shipped_ts

    result = {"check": "Log shipper", "status": "fail"}

    if not _shipper_alive():
        result["detail"] = (
            "Not running — client logs are not reaching the allocator. "
            "Run `lablink client register` to restart it."
        )
        return result

    last = read_last_shipped_ts(STATE_FILE)
    if last is None:
        result["status"] = "warn"
        result["detail"] = (
            "Running, but has never shipped a batch. Normal for the first "
            "minute after registering; otherwise check the allocator URL "
            "and client secret."
        )
        return result

    try:
        shipped_at = datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        result["status"] = "warn"
        result["detail"] = f"Running; unparseable last-shipped value {last!r}"
        return result

    current = now if now is not None else time.time()
    age_s = current - shipped_at.timestamp()
    if age_s > SHIPPER_STALE_AFTER_S:
        result["status"] = "warn"
        result["detail"] = (
            f"Running, but last shipped {_format_age(age_s)} ago ({last}). "
            "The process is up but nothing is reaching the allocator."
        )
        return result

    result["status"] = "pass"
    result["detail"] = f"Running; last shipped {last}"
    return result


def run_client_doctor() -> None:
    """Run the BYO-client checks and print a results table."""
    console.print()
    console.print(
        Panel(
            "[bold]LabLink Client Doctor[/bold]\n"
            "Checking this machine's BYO client.",
            border_style="cyan",
        )
    )
    console.print()

    checks = [
        _check_client_registered(),
        _check_client_container(),
        _check_log_shipper(),
    ]

    _render_checks(
        checks,
        pass_message=(
            "[green]All checks passed.[/green] "
            "This client is registered and shipping logs."
        ),
        fail_message=(
            "[yellow]Some checks need attention.[/yellow] "
            "Most are fixed by re-running `lablink client register`."
        ),
    )


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

    cfg = _load_config_safe()
    provider = getattr(cfg, "provider", None) if cfg else None

    if provider == "manual":
        _check_manual_prereqs()
    else:
        _check_aws_prereqs()
