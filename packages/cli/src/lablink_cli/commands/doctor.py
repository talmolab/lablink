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

from lablink_cli.docker import Docker, DockerUnavailable, default_docker

console = Console()

DEFAULT_CONFIG = Path.home() / ".lablink" / "config.yaml"

STATUS_STYLES = {
    "pass": "[green]PASS[/green]",
    "fail": "[red]FAIL[/red]",
    "warn": "[yellow]WARN[/yellow]",
}

# The S3 backend corrupts state below this version: an aws-sdk-go-v2 bug leaves
# the PutObject body non-seekable, so a retried state upload fails with "failed
# to rewind transport stream for retry" *after* apply/destroy has already run.
#
# The fix was a pure SDK bump (aws/aws-sdk-go-v2#2485), so what matters is the
# vendored SDK, not the release number. OpenTofu pinned aws-sdk-go-v2 v1.23.2
# from 1.6.0 all the way through 1.9.x — older than the v1.24.0 the bug was
# reported against, and well short of the v1.25.3 that carries the fix. 1.10.0
# is the first release past it (v1.36.0). Do not "translate" OpenTofu's old
# 1.9.0 floor across by number: OpenTofu 1.9 predates the fix.
MIN_OPENTOFU_VERSION = (1, 10, 0)


def _parse_version(version: str) -> tuple[int, ...] | None:
    """Parse a dotted version string into a comparable tuple.

    Args:
        version: Version string such as ``"1.12.5"``. Pre-release suffixes
            (``"1.10.0-beta1"``) are truncated at the first hyphen.

    Returns:
        Tuple of at least three integers, or None if the string is not
        parseable.
    """
    try:
        parts = tuple(int(part) for part in version.split("-")[0].split("."))
    except (AttributeError, ValueError):
        return None
    # Pad to three components so "1.10" compares equal to "1.10.0" instead of
    # sorting below it — the minimum below sits exactly on a .0 boundary.
    return parts + (0,) * (3 - len(parts))


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


def _check_opentofu() -> dict:
    """Check that OpenTofu is installed and return version."""
    result = {"check": "OpenTofu installed", "status": "fail"}

    path = shutil.which("tofu")
    if not path:
        result["detail"] = (
            "tofu not found on PATH. "
            "Install from https://opentofu.org/docs/intro/install/"
        )
        return result

    try:
        proc = subprocess.run(
            ["tofu", "version", "-json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode == 0:
            info = json.loads(proc.stdout)
            # OpenTofu keeps OpenTofu's key name here.
            version = info.get(
                "terraform_version", "unknown"
            )
            parsed = _parse_version(version)
            minimum = ".".join(str(p) for p in MIN_OPENTOFU_VERSION)
            if parsed is not None and parsed < MIN_OPENTOFU_VERSION:
                result["status"] = "fail"
                result["detail"] = (
                    f"v{version} ({path}) is too old — need {minimum}+. "
                    "Older versions vendor an aws-sdk-go-v2 that corrupts "
                    "state on S3 upload retries instead of failing cleanly "
                    "(aws/aws-sdk-go-v2#2485)."
                )
            else:
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
    """Check that the S3 bucket for OpenTofu state exists."""
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
        supported = ", ".join(AMI_MAP)
        result["status"] = "fail"
        result["detail"] = (
            f"AMI IDs are region-scoped and LabLink's images exist only in "
            f"{supported}, so app.region '{region}' cannot deploy — OpenTofu "
            f"refuses to plan. Set app.region to one of: {supported}"
        )

    return result


def _check_aws_prereqs() -> None:
    """Run the AWS-specific pre-flight checks and print a results table."""
    checks: list[dict] = []

    # 1. OpenTofu
    checks.append(_check_opentofu())

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


def _check_manual_prereqs(*, docker: Docker | None = None) -> None:
    """Check that docker + docker compose are available (manual provider)."""
    docker = docker or default_docker()

    docker_path = docker.path()
    if docker_path:
        console.print(f"[green]✓[/green] docker: {docker_path}")
    else:
        console.print("[red]✗[/red] docker: not found")

    # docker-compose v2 is a subcommand, not a separate binary
    try:
        result = docker.compose(None, "version")
    except DockerUnavailable:
        console.print(
            "[red]✗[/red] docker compose: missing "
            "(install the Compose plugin)"
        )
        return
    if result.ok:
        console.print("[green]✓[/green] docker compose: available")
    else:
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


def _check_client_container(docker: Docker) -> dict:
    """Report the lablink-client container's state.

    Doubles as the docker-daemon check: `container_status` returns
    "daemon_error" when the daemon is unreachable, so a separate probe would
    only duplicate the same `docker inspect` call.
    """
    from lablink_cli.commands.register import CONTAINER_NAME

    result = {"check": "Client container", "status": "fail"}
    status = docker.container_status(CONTAINER_NAME)

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


def _check_log_shipper(docker: Docker) -> dict:
    """Check the in-container ship_logs worker is running.

    The shipper lives inside the client container — start.sh feeds every
    service's output through the client package's ship_logs worker when
    SHIP_LOGS=1 — so the probe is a pgrep inside the container. The old
    host-side staleness check (lablink#428's alive-but-not-shipping
    hazard) moved in-container with it: a worker that can't reach the
    allocator says so in `docker logs lablink-client`
    ("ship_logs: dropped N lines after retries").
    """
    from lablink_cli.commands.register import CONTAINER_NAME

    result = {"check": "Log shipper", "status": "fail"}

    probe = docker.exec_in(CONTAINER_NAME, ["pgrep", "-f", "ship_logs"])
    if probe.ok:
        result["status"] = "pass"
        result["detail"] = "ship_logs worker running inside the container"
        return result

    result["detail"] = (
        "No ship_logs worker inside the container — client logs are not "
        "reaching the allocator. The container is either down (see the "
        "check above), running an image that predates in-container "
        "shipping, or missing SHIP_LOGS=1 in its env. Re-run "
        "`lablink client register --force` to recreate it."
    )
    return result


def run_client_doctor(*, docker: Docker | None = None) -> None:
    """Run the BYO-client checks and print a results table."""
    docker = docker or default_docker()
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
        _check_client_container(docker),
        _check_log_shipper(docker),
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
