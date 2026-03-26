"""Deploy and destroy LabLink infrastructure with Terraform."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from lablink_allocator_service.conf.structured_config import Config

from lablink_cli.commands.setup import check_credentials, _get_session
from lablink_cli.config.schema import (
    config_to_dict,
    save_config,
)

console = Console()

# Bundled terraform files shipped with the CLI package
TERRAFORM_SRC = (
    Path(__file__).resolve().parent.parent / "terraform"
)

# Working directory for terraform operations
DEPLOY_DIR = Path.home() / ".lablink" / "deploy"


def _prepare_working_dir(cfg: Config) -> Path:
    """Set up the Terraform working directory.

    Copies bundled .tf files and writes config/config.yaml.
    Returns the working directory path.
    """
    deploy_dir = DEPLOY_DIR
    deploy_dir.mkdir(parents=True, exist_ok=True)

    # Copy .tf files and user_data.sh (overwrite to stay current)
    for src_file in TERRAFORM_SRC.glob("*.tf"):
        shutil.copy2(src_file, deploy_dir / src_file.name)

    # Copy user_data.sh
    user_data_src = TERRAFORM_SRC / "user_data.sh"
    if user_data_src.exists():
        shutil.copy2(user_data_src, deploy_dir / "user_data.sh")

    # Copy .terraform.lock.hcl if present (pins provider versions)
    lock_file = TERRAFORM_SRC / ".terraform.lock.hcl"
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
        # Check ~/.lablink/ first, then bundled terraform dir
        user_script = (
            Path.home() / ".lablink" / "custom-startup.sh"
        )
        if user_script.exists():
            src_startup = user_script
        else:
            src_startup = TERRAFORM_SRC / cfg.startup_script.path

        if src_startup.exists():
            dest_startup = (
                deploy_dir / "config" / "custom-startup.sh"
            )
            dest_startup.parent.mkdir(
                parents=True, exist_ok=True
            )
            shutil.copy2(src_startup, dest_startup)

    # Override the hardcoded region in main.tf
    main_tf = deploy_dir / "main.tf"
    content = main_tf.read_text()
    content = content.replace(
        'region = "us-west-2"',
        f'region = "{cfg.app.region}"',
    )
    main_tf.write_text(content)

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

    args = [
        "init",
        "-backend-config=key=lablink/terraform.tfstate",
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


def run_deploy(cfg: Config) -> None:
    """Deploy LabLink infrastructure."""
    console.print()
    console.print(
        Panel(
            "[bold]LabLink Deploy[/bold]\n"
            f"Region: {cfg.app.region}  |  State: S3 (remote)",
            border_style="cyan",
        )
    )
    console.print()

    # Validate AWS credentials
    check_credentials(_get_session(cfg.app.region))

    # Prepare working directory
    deploy_dir = _prepare_working_dir(cfg)

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

    # Terraform init
    _terraform_init(deploy_dir, cfg)

    # Terraform plan
    console.print("[bold]Step 2/3:[/bold] Terraform plan")
    _run_terraform(["plan", "-out=tfplan"], cwd=deploy_dir)
    console.print()

    # Confirm before apply
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

    # Wait and run health checks
    import time

    from lablink_cli.commands.status import (
        check_http,
        run_status,
    )

    has_ssl = cfg.ssl.provider != "none"
    max_wait = 300 if has_ssl else 120
    interval = 15
    elapsed = 0

    console.print(
        f"[bold]Waiting for allocator to become healthy"
        f" (up to {max_wait // 60} min)...[/bold]"
    )

    # Determine URL to poll
    if cfg.dns.enabled and cfg.dns.domain:
        scheme = "https" if has_ssl else "http"
        poll_url = f"{scheme}://{cfg.dns.domain}"
    else:
        poll_url = None

    # Initial wait for instance boot + docker pull
    time.sleep(60)
    elapsed = 60

    while elapsed < max_wait:
        if poll_url:
            result = check_http(poll_url)
            if result["status"] == "pass":
                console.print(
                    f"[green]Allocator healthy after"
                    f" {elapsed}s[/green]"
                )
                break
        time.sleep(interval)
        elapsed += interval
        console.print(
            f"[dim]  Waiting... ({elapsed}s / {max_wait}s)[/dim]"
        )
    else:
        console.print(
            "[yellow]Timed out waiting for healthy status."
            " Running status check anyway...[/yellow]"
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


def run_destroy(cfg: Config) -> None:
    """Destroy LabLink infrastructure."""
    # Validate AWS credentials
    check_credentials(_get_session(cfg.app.region))

    deploy_dir = DEPLOY_DIR

    if not deploy_dir.exists():
        console.print(
            "[red]No deployment found.[/red] "
            f"Expected working directory: {deploy_dir}"
        )
        raise SystemExit(1)

    # Check for terraform state
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
            "This will tear down ALL LabLink infrastructure.\n"
            f"Region: {cfg.app.region}  |  State: S3 (remote)",
            border_style="red",
        )
    )
    console.print()

    # Refresh config in deploy dir (passwords needed for
    # terraform to read the config, but destroy doesn't use them
    # — write placeholder values)
    config_path = deploy_dir / "config" / "config.yaml"
    cfg_dict = config_to_dict(cfg)
    cfg_dict["app"]["admin_user"] = "DESTROY_PLACEHOLDER"
    cfg_dict["app"]["admin_password"] = "DESTROY_PLACEHOLDER"
    cfg_dict["db"]["password"] = "DESTROY_PLACEHOLDER"

    import yaml

    with open(config_path, "w") as f:
        yaml.dump(
            cfg_dict,
            f,
            default_flow_style=False,
            sort_keys=False,
        )

    # Re-init if needed
    if (deploy_dir / "backend.tf").exists():
        _terraform_init(deploy_dir, cfg)

    # Check for running client VMs
    from lablink_cli.commands.status import check_client_vms

    client_vms = check_client_vms(cfg)
    running_vms = [
        vm for vm in client_vms if vm["state"] == "running"
    ]
    if running_vms:
        console.print(
            f"[bold yellow]{len(running_vms)} client VM(s) "
            f"still running:[/bold yellow]"
        )
        for vm in running_vms:
            console.print(
                f"  {vm['name']} ({vm['instance_id']}) "
                f"— {vm['type']}"
            )
        console.print(
            "  These will be terminated as part of destroy."
        )
        console.print()

    # Confirm
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

    # Terminate client VMs first
    if running_vms:
        console.print(
            "[bold]Terminating client VMs...[/bold]"
        )
        import boto3

        ec2 = boto3.client(
            "ec2", region_name=cfg.app.region
        )
        instance_ids = [
            vm["instance_id"] for vm in running_vms
        ]
        ec2.terminate_instances(InstanceIds=instance_ids)
        console.print(
            f"  [green]terminated[/green] "
            f"{len(instance_ids)} client VM(s)"
        )
        # Wait for termination
        waiter = ec2.get_waiter("instance_terminated")
        waiter.wait(InstanceIds=instance_ids)
        console.print(
            "  [green]all client VMs terminated[/green]"
        )
        console.print()

    # Terraform destroy
    console.print("[bold]Destroying infrastructure...[/bold]")
    _run_terraform(
        ["destroy", "-auto-approve"], cwd=deploy_dir
    )
    console.print()

    # Clean up deploy directory
    import shutil

    shutil.rmtree(deploy_dir)
    console.print(
        f"  [green]cleaned[/green] {deploy_dir}"
    )
    console.print()
    console.print("[bold]Infrastructure destroyed.[/bold]")
