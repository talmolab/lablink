"""Deploy and destroy LabLink infrastructure with Terraform."""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from lablink_allocator_service.conf.structured_config import Config

from lablink_cli.commands.setup import check_credentials, _get_session
from lablink_cli.commands.status import check_health_endpoint
from lablink_cli.commands.utils import (
    get_allocator_url,
    get_deploy_dir,
    resolve_admin_credentials,
)
from lablink_cli.api import (
    AllocatorAPI,
    AllocatorAuthError,
    AllocatorError,
    AllocatorNotFoundError,
    AllocatorUnavailableError,
)
from lablink_cli.commands.export_metrics import run_export_metrics
from lablink_cli.config.schema import config_to_dict, save_config
from lablink_cli.deployment_metrics import (
    DeploymentMetrics,
    cache_path_for,
    phase_timer,
    write_metrics,
)
from lablink_cli.terraform_source import get_terraform_files

console = Console()


def _prepare_working_dir(
    cfg: Config,
    *,
    template_version: str | None = None,
    terraform_bundle: str | None = None,
) -> Path:
    """Set up the Terraform working directory.

    Downloads (or loads from cache/bundle) the template's .tf files,
    copies them into the deploy directory, and writes config/config.yaml.
    """
    from lablink_cli import TEMPLATE_VERSION

    version = template_version or TEMPLATE_VERSION
    skip_checksum = template_version is not None

    if template_version:
        console.print(
            f"  [yellow]Warning: using override version "
            f"{template_version}, skipping checksum "
            f"verification[/yellow]"
        )

    tf_source = get_terraform_files(
        version,
        bundle_path=terraform_bundle,
        skip_checksum=skip_checksum,
    )

    deploy_dir = get_deploy_dir(cfg)
    deploy_dir.mkdir(parents=True, exist_ok=True)

    # Copy .tf and .hcl files
    for src_file in tf_source.glob("*.tf"):
        shutil.copy2(src_file, deploy_dir / src_file.name)
    for src_file in tf_source.glob("*.hcl"):
        shutil.copy2(src_file, deploy_dir / src_file.name)

    # Copy user_data.sh
    user_data_src = tf_source / "user_data.sh"
    if user_data_src.exists():
        shutil.copy2(user_data_src, deploy_dir / "user_data.sh")

    # Copy .terraform.lock.hcl if present (pins provider versions)
    lock_file = tf_source / ".terraform.lock.hcl"
    if lock_file.exists():
        shutil.copy2(
            lock_file, deploy_dir / ".terraform.lock.hcl"
        )

    # Write config/config.yaml from the Config object
    config_dir = deploy_dir / "config"
    config_dir.mkdir(exist_ok=True)
    save_config(cfg, config_dir / "config.yaml")

    # Copy custom startup script if configured
    if cfg.startup_script.enabled and cfg.startup_script.path:
        user_script = (
            Path.home() / ".lablink" / "custom-startup.sh"
        )
        if user_script.exists():
            src_startup = user_script
        else:
            src_startup = tf_source / cfg.startup_script.path

        if src_startup.exists():
            dest_startup = (
                deploy_dir / "config" / "custom-startup.sh"
            )
            dest_startup.parent.mkdir(
                parents=True, exist_ok=True
            )
            shutil.copy2(src_startup, dest_startup)

    return deploy_dir


def _run_terraform(
    args: list[str],
    cwd: Path,
    check: bool = True,
) -> int:
    """Run a terraform command with live-streamed output."""
    cmd = ["terraform"] + args
    console.print(
        f"  [dim]$ {' '.join(cmd)}[/dim]"
    )

    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    if proc.stdout:
        for line in proc.stdout:
            console.print(
                f"  {line}", end="", highlight=False
            )

    proc.wait()

    if check and proc.returncode != 0:
        console.print(
            f"\n  [red]terraform {args[0]} failed "
            f"(exit code {proc.returncode})[/red]"
        )
        raise SystemExit(proc.returncode)

    return proc.returncode


def _terraform_init(
    deploy_dir: Path,
    cfg: Config,
) -> None:
    """Run terraform init with S3 remote backend."""
    console.print("[bold]Step 1/3:[/bold] Terraform init")

    # Use -reconfigure if .terraform already exists (avoids
    # "backend configuration changed" errors).
    reconfigure = (deploy_dir / ".terraform").exists()

    # Resolve bucket name from AWS account
    import boto3

    account_id = (
        boto3.client(
            "sts", region_name=cfg.app.region
        )
        .get_caller_identity()["Account"]
    )
    bucket_name = f"lablink-tf-state-{account_id}"

    # State key scoped by deployment_name and environment
    state_key = (
        f"{cfg.deployment_name}/{cfg.environment}"
        f"/terraform.tfstate"
    )

    args = [
        "init",
        f"-backend-config=key={state_key}",
        f"-backend-config=bucket={bucket_name}",
        f"-backend-config=region={cfg.app.region}",
        "-backend-config=dynamodb_table=lock-table",
        "-backend-config=encrypt=true",
    ]
    if reconfigure:
        args.append("-reconfigure")
    _run_terraform(args, cwd=deploy_dir)

    console.print()


def _prompt_passwords() -> dict[str, str]:
    """Prompt for admin and database passwords at deploy time."""
    import getpass

    console.print(
        "[bold]Credentials[/bold] "
        "(not stored in config, passed to Terraform only)"
    )

    admin_user = input("  Admin username [admin]: ").strip()
    if not admin_user:
        admin_user = "admin"

    admin_pw = getpass.getpass("  Admin password: ")
    if not admin_pw:
        console.print("  [red]Admin password is required[/red]")
        raise SystemExit(1)

    db_pw = getpass.getpass("  Database password: ")
    if not db_pw:
        console.print(
            "  [red]Database password is required[/red]"
        )
        raise SystemExit(1)

    console.print()
    return {
        "admin_user": admin_user,
        "admin_password": admin_pw,
        "db_password": db_pw,
    }


def _poll_allocator_health(
    poll_url: str,
    *,
    max_wait: int = 120,
) -> dict:
    """Poll the allocator health endpoint with adaptive intervals.

    Intervals: 3s for first 30s, 5s for 30-90s, 10s after 90s.

    Returns dict with:
      - healthy: bool
      - elapsed: float (seconds from start to healthy or timeout)
      - timed_out: bool
      - uptime_seconds: float | None (from allocator's self-reported uptime)
    """
    start = time.monotonic()
    elapsed = 0.0

    while elapsed < max_wait:
        result = check_health_endpoint(poll_url)
        elapsed = time.monotonic() - start

        if result["healthy"]:
            return {
                "healthy": True,
                "elapsed": elapsed,
                "timed_out": False,
                "uptime_seconds": result.get("uptime_seconds"),
            }

        # Adaptive interval based on elapsed time
        if elapsed < 30:
            interval = 3
        elif elapsed < 90:
            interval = 5
        else:
            interval = 10

        console.print(
            f"[dim]  {result['status']}... ({elapsed:.0f}s / {max_wait}s)[/dim]"
        )
        time.sleep(interval)
        elapsed = time.monotonic() - start

    return {
        "healthy": False,
        "elapsed": elapsed,
        "timed_out": True,
        "uptime_seconds": None,
    }


def run_deploy(
    cfg: Config,
    *,
    template_version: str | None = None,
    terraform_bundle: str | None = None,
) -> None:
    """Deploy LabLink infrastructure."""
    from lablink_cli import TEMPLATE_VERSION

    console.print()
    console.print(
        Panel(
            "[bold]LabLink Deploy[/bold]\n"
            f"Deployment: {cfg.deployment_name}  |  "
            f"Environment: {cfg.environment}\n"
            f"Region: {cfg.app.region}  |  State: S3 (remote)",
            border_style="cyan",
        )
    )
    console.print()

    # Validate AWS credentials
    check_credentials(_get_session(cfg.app.region))

    # Prepare working directory
    deploy_dir = _prepare_working_dir(
        cfg,
        template_version=template_version,
        terraform_bundle=terraform_bundle,
    )

    # Prompt for credentials
    passwords = _prompt_passwords()

    # Write credentials into deploy dir config for Terraform
    # (deploy dir only, never persisted to ~/.lablink/)
    import yaml

    config_path = deploy_dir / "config" / "config.yaml"
    with open(config_path) as f:
        cfg_dict = yaml.safe_load(f)

    cfg_dict["app"]["admin_user"] = passwords["admin_user"]
    cfg_dict["app"]["admin_password"] = passwords[
        "admin_password"
    ]
    cfg_dict["db"]["password"] = passwords["db_password"]

    with open(config_path, "w") as f:
        yaml.dump(
            cfg_dict,
            f,
            default_flow_style=False,
            sort_keys=False,
        )

    # Initialize deployment metrics — written incrementally so failed
    # or interrupted deploys still leave a useful partial record on disk.
    has_ssl = cfg.ssl.provider != "none"
    deploy_start_dt = datetime.now(timezone.utc)
    metrics = DeploymentMetrics(
        deployment_name=cfg.deployment_name,
        region=cfg.app.region,
        template_version=template_version or TEMPLATE_VERSION,
        ssl_enabled=has_ssl,
        allocator_deploy_start_time=deploy_start_dt.isoformat(),
    )
    metrics_path = cache_path_for(cfg.deployment_name, deploy_start_dt)
    write_metrics(metrics_path, metrics)

    try:
        # Terraform init
        with phase_timer(
            metrics, "allocator_terraform_init_duration_seconds", metrics_path
        ):
            _terraform_init(deploy_dir, cfg)

        # Terraform plan — pass deployment_name and environment
        console.print("[bold]Step 2/3:[/bold] Terraform plan")
        with phase_timer(
            metrics, "allocator_terraform_plan_duration_seconds", metrics_path
        ):
            _run_terraform(
                [
                    "plan",
                    f"-var=deployment_name={cfg.deployment_name}",
                    f"-var=environment={cfg.environment}",
                    f"-var=region={cfg.app.region}",
                    "-out=tfplan",
                ],
                cwd=deploy_dir,
            )
        console.print()

        # Confirm before apply (user think-time intentionally excluded from phases)
        console.print(
            "[bold yellow]Review the plan above.[/bold yellow] "
            "Type 'yes' to apply: ",
            end="",
        )
        answer = input()
        if answer.strip().lower() != "yes":
            console.print(
                "[dim]Cancelled. No resources were created.[/dim]"
            )
            raise SystemExit(0)
        console.print()

        # Terraform apply
        console.print("[bold]Step 3/3:[/bold] Terraform apply")
        with phase_timer(
            metrics, "allocator_terraform_apply_duration_seconds", metrics_path
        ):
            _run_terraform(
                ["apply", "-auto-approve", "tfplan"], cwd=deploy_dir
            )
        console.print()

        # Show outputs
        console.print("[bold]Deployment complete![/bold]")
        _run_terraform(
            ["output"], cwd=deploy_dir, check=False
        )
        console.print()

        # --- Deployment timing ---
        from lablink_cli.commands.status import run_status
        from lablink_cli.commands.utils import get_terraform_outputs

        outputs = get_terraform_outputs(deploy_dir)
        ec2_ip = outputs.get("ec2_public_ip", "")

        max_wait = 300 if has_ssl else 120

        # Phase 1: Poll EC2 IP directly for allocator readiness.
        # Uses port 80 (nginx) — the EC2 security group does not expose
        # Flask's 5000 externally; nginx reverse-proxies to it internally.
        if ec2_ip:
            direct_url = f"http://{ec2_ip}"
            console.print(
                f"[bold]Waiting for allocator to become healthy"
                f" (up to {max_wait // 60} min)...[/bold]"
            )
            with phase_timer(
                metrics,
                "allocator_health_check_duration_seconds",
                metrics_path,
            ):
                poll_result = _poll_allocator_health(
                    direct_url, max_wait=max_wait
                )

            if poll_result["healthy"]:
                console.print(
                    f"[green]Allocator healthy after"
                    f" {poll_result['elapsed']:.0f}s[/green]"
                )
            else:
                console.print(
                    "[yellow]Timed out waiting for healthy status."
                    " Running status check anyway...[/yellow]"
                )
        else:
            console.print(
                "[yellow]No EC2 IP found in Terraform outputs."
                " Skipping health check.[/yellow]"
            )
            poll_result = {"healthy": False, "elapsed": 0, "timed_out": True}

        # Mark success and record total time (sum of timed phases — excludes
        # user prompt time, which is the reproducible "machine work" measure).
        deploy_end_dt = datetime.now(timezone.utc)
        metrics.allocator_deploy_end_time = deploy_end_dt.isoformat()
        metrics.allocator_total_deployment_duration_seconds = round(
            sum(
                v
                for v in (
                    metrics.allocator_terraform_init_duration_seconds,
                    metrics.allocator_terraform_plan_duration_seconds,
                    metrics.allocator_terraform_apply_duration_seconds,
                    metrics.allocator_health_check_duration_seconds,
                )
                if v is not None
            ),
            3,
        )
        metrics.status = "success"
        write_metrics(metrics_path, metrics)

    except Exception as e:
        # Persist the failure so we have a record of what timed out / blew up.
        # SystemExit (user cancellation, terraform exit code) is a BaseException
        # subclass and intentionally NOT caught here — cancellation leaves the
        # file in 'in_progress' state, which is correct semantics.
        metrics.status = "failed"
        metrics.error = str(e)
        write_metrics(metrics_path, metrics)
        raise

    # Phase 2: If DNS/SSL configured, verify endpoint reachability
    if cfg.dns.enabled and cfg.dns.domain and poll_result["healthy"]:
        from lablink_cli.commands.status import check_http

        scheme = "https" if has_ssl else "http"
        endpoint_url = f"{scheme}://{cfg.dns.domain}"
        console.print(
            f"[bold]Checking endpoint reachability at"
            f" {endpoint_url}...[/bold]"
        )

        dns_start = time.monotonic()
        dns_max = 180 if has_ssl else 60
        dns_elapsed = 0.0

        while dns_elapsed < dns_max:
            http_result = check_http(endpoint_url)
            dns_elapsed = time.monotonic() - dns_start
            if http_result["status"] == "pass":
                console.print(
                    f"[green]Endpoint reachable after"
                    f" {dns_elapsed:.0f}s[/green]"
                )
                break
            time.sleep(10)
            dns_elapsed = time.monotonic() - dns_start
        else:
            console.print(
                f"[yellow]Endpoint {endpoint_url} not yet"
                f" reachable after {dns_elapsed:.0f}s."
                f" DNS/SSL may still be propagating.[/yellow]"
            )

    console.print()
    run_status(cfg)
    console.print()

    console.print(
        f"[dim]Working directory:[/dim] {deploy_dir}"
    )
    console.print(
        "[dim]To tear down:[/dim] [bold]lablink destroy[/bold]"
    )
    console.print(
        "[dim]To export deployment metrics:[/dim] "
        "[bold]lablink export-metrics --allocator[/bold]"
    )


def _destroy_client_vms(
    cfg: Config,
    admin_user: str,
    admin_pw: str,
) -> None:
    """Destroy client VMs via the allocator API."""
    allocator_url = get_allocator_url(cfg)
    if not allocator_url:
        console.print(
            "[yellow]Could not determine allocator "
            "URL — skipping client VM destroy.[/yellow]\n"
            "Client VMs will be terminated when the "
            "allocator is destroyed."
        )
        return

    console.print(
        "[bold]Destroying client VMs via "
        "allocator...[/bold]"
    )
    console.print(
        f"  [dim]POST {allocator_url}/destroy[/dim]"
    )

    api = AllocatorAPI(
        allocator_url, admin_user, admin_pw, cfg.ssl.provider
    )
    try:
        api.destroy_vms()
        console.print(
            "  [green]client VMs destroyed[/green]"
        )
    except AllocatorAuthError:
        console.print(
            "  [red]Authentication failed.[/red] "
            "Check your admin credentials."
        )
        raise SystemExit(1)
    except AllocatorNotFoundError:
        console.print(
            "  [yellow]No client VMs were "
            "launched.[/yellow] Skipping "
            "client destroy."
        )
        console.print(
            "  Continuing with allocator "
            "terraform destroy..."
        )
    except AllocatorUnavailableError as e:
        console.print(
            f"  [yellow]Could not connect to "
            f"allocator:[/yellow] {e}"
        )
        console.print(
            "  Continuing with allocator "
            "terraform destroy..."
        )
    except AllocatorError as e:
        console.print(
            f"  [red]Client destroy failed:[/red] {e}"
        )
        raise SystemExit(1)

    console.print()


def _terraform_destroy(
    deploy_dir: Path,
    cfg: Config,
    admin_user: str,
    admin_pw: str,
) -> None:
    """Refresh config, re-init terraform, destroy, and clean up."""
    import yaml

    config_path = deploy_dir / "config" / "config.yaml"
    cfg_dict = config_to_dict(cfg)
    cfg_dict["app"]["admin_user"] = admin_user
    cfg_dict["app"]["admin_password"] = admin_pw
    cfg_dict["db"]["password"] = "DESTROY_PLACEHOLDER"

    with open(config_path, "w") as f:
        yaml.dump(
            cfg_dict,
            f,
            default_flow_style=False,
            sort_keys=False,
        )

    if (deploy_dir / "backend.tf").exists():
        _terraform_init(deploy_dir, cfg)

    console.print(
        "[bold]Destroying allocator "
        "infrastructure...[/bold]"
    )
    _run_terraform(
        [
            "destroy",
            "-auto-approve",
            f"-var=deployment_name={cfg.deployment_name}",
            f"-var=environment={cfg.environment}",
            f"-var=region={cfg.app.region}",
        ],
        cwd=deploy_dir,
    )
    console.print()

    shutil.rmtree(deploy_dir)
    console.print(
        f"  [green]cleaned[/green] {deploy_dir}"
    )
    console.print()
    console.print("[bold]Infrastructure destroyed.[/bold]")


def run_destroy(cfg: Config) -> None:
    """Destroy LabLink infrastructure."""
    check_credentials(_get_session(cfg.app.region))

    deploy_dir = get_deploy_dir(cfg)

    if not deploy_dir.exists():
        console.print(
            "[red]No deployment found.[/red] "
            f"Expected working directory: {deploy_dir}"
        )
        raise SystemExit(1)

    has_state = (
        (deploy_dir / "terraform.tfstate").exists()
        or (deploy_dir / ".terraform").exists()
    )
    if not has_state:
        console.print(
            "[red]No Terraform state found.[/red] "
            "Nothing to destroy."
        )
        raise SystemExit(1)

    console.print()
    console.print(
        Panel(
            "[bold red]LabLink Destroy[/bold red]\n"
            "This will tear down ALL LabLink infrastructure\n"
            "(client VMs via allocator, then the allocator "
            "itself via Terraform).\n"
            f"Deployment: {cfg.deployment_name}  |  "
            f"Environment: {cfg.environment}\n"
            f"Region: {cfg.app.region}  |  State: S3 (remote)",
            border_style="red",
        )
    )
    console.print()

    admin_user, admin_pw = resolve_admin_credentials(cfg)

    console.print(
        "[bold yellow]Are you sure?[/bold yellow] "
        "Type 'yes' to confirm: ",
        end="",
    )
    answer = input()
    if answer.strip().lower() != "yes":
        console.print("[dim]Cancelled.[/dim]")
        raise SystemExit(0)
    console.print()

    # Offer one last chance to export metrics — once destroy runs, the
    # allocator's per-VM metrics are gone forever. Default = yes.
    console.print(
        "[bold]Export metrics before destroying?[/bold] [Y/n]: ",
        end="",
    )
    export_answer = input().strip().lower()
    if export_answer in ("", "y", "yes"):
        # Catch both Exception and SystemExit — run_export_metrics raises
        # SystemExit(1) on network/HTTP failures (it doubles as a CLI entry
        # point), and we must not let that abort the destroy itself.
        # KeyboardInterrupt is intentionally left uncaught so Ctrl-C aborts.
        try:
            run_export_metrics(cfg, client=True, allocator=True)
        except (Exception, SystemExit) as e:
            console.print(
                f"[yellow]Export failed: {e}. "
                f"Continuing with destroy...[/yellow]"
            )
    console.print()

    _destroy_client_vms(cfg, admin_user, admin_pw)
    _terraform_destroy(deploy_dir, cfg, admin_user, admin_pw)
