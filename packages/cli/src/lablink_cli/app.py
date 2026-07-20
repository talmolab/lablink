"""LabLink CLI entry point."""

from pathlib import Path

import typer

from lablink_cli.config.schema import load_config

app = typer.Typer(
    name="lablink",
)

client_app = typer.Typer(
    name="client",
    help="Manage the client fleet (register/launch/unregister).",
)
app.add_typer(client_app, name="client")

DEFAULT_CONFIG = Path.home() / ".lablink" / "config.yaml"


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import version

        from lablink_cli import TEMPLATE_VERSION

        typer.echo(f"lablink-cli {version('lablink-cli')}")
        typer.echo(f"lablink-template {TEMPLATE_VERSION.lstrip('v')}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    _version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show CLI and template versions and exit.",
    ),
) -> None:
    """Deploy and manage LabLink teaching lab infrastructure."""
    if ctx.invoked_subcommand is not None:
        return

    if not DEFAULT_CONFIG.exists():
        from rich.console import Console
        from rich.panel import Panel

        Console().print(
            Panel(
                "Welcome to LabLink. First-time setup:\n\n"
                "  1. [bold]lablink configure[/bold]   "
                "create config (AWS or manual/BYO provider)\n"
                "  2. [bold]lablink doctor[/bold]      "
                "verify prerequisites for your provider\n"
                "  3. [bold]lablink deploy[/bold]      "
                "deploy the allocator\n\n"
                "For the full command list, run 'lablink --help'.",
                border_style="cyan",
                title="Getting started",
                title_align="left",
            )
        )
        raise typer.Exit()

    typer.echo(ctx.get_help())


def _load_cfg(config: str | None):
    """Load config from path, exit with message if not found."""
    from lablink_cli.config.schema import load_config

    config_path = Path(config) if config else DEFAULT_CONFIG
    if not config_path.exists():
        typer.echo(
            f"Config not found: {config_path}\n"
            "Run 'lablink configure' first to generate a config."
        )
        raise typer.Exit(1)
    return load_config(config_path)


@app.command(rich_help_panel="Setup")
def configure(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
) -> None:
    """Create or edit the LabLink configuration.

    Launches a TUI wizard to generate or modify config.yaml,
    then automatically creates the AWS resources needed for
    Terraform remote state (S3 bucket + DynamoDB lock table).
    Manual-provider configs skip the AWS setup step.
    """
    from lablink_cli.tui.wizard import ConfigWizard

    config_path = Path(config) if config else DEFAULT_CONFIG

    existing = None
    if config_path.exists():
        existing = load_config(config_path)

    wizard = ConfigWizard(
        existing_config=existing, save_path=config_path
    )
    wizard.run()

    # After the wizard saves config, run AWS setup automatically
    if not config_path.exists():
        # User quit the wizard without saving
        return

    cfg_after = load_config(config_path)
    if cfg_after.provider == "manual":
        from rich.console import Console

        Console().print(
            "[dim]Manual provider doesn't need AWS state resources — "
            "skipping setup. Run `lablink deploy` next.[/dim]"
        )
        return

    from lablink_cli.commands.setup import run_setup

    run_setup(cfg_after, config_path=config_path)


@app.command(rich_help_panel="Setup")
def setup(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
) -> None:
    """Provision provider-specific bootstrap resources.

    AWS provider: creates the S3 bucket and DynamoDB lock table used
    for Terraform remote state. Automatically run during 'lablink
    configure'; use this command to recreate the resources if they
    were deleted.

    Manual provider: no bootstrap resources are needed; this command
    is a no-op (a friendly message is printed).
    """
    from lablink_cli.commands.setup import run_setup

    config_path = Path(config) if config else DEFAULT_CONFIG
    run_setup(_load_cfg(config), config_path=config_path)


@app.command(rich_help_panel="Deployment")
def deploy(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
    template_version: str = typer.Option(
        None,
        "--template-version",
        help="Override the pinned template version (e.g. v0.2.0). "
        "Skips checksum verification. AWS provider only.",
    ),
    terraform_bundle: str = typer.Option(
        None,
        "--terraform-bundle",
        help="Path to a local template tarball for offline deploys. "
        "AWS provider only.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompts. Does not bypass credential prompts "
        "(admin password still required interactively).",
    ),
) -> None:
    """Deploy LabLink infrastructure (AWS Terraform or docker-compose)."""
    cfg = _load_cfg(config)
    if cfg.provider == "manual":
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        run_deploy_compose(cfg, yes=yes)
        return

    from lablink_cli.commands.deploy import run_deploy

    run_deploy(
        cfg,
        template_version=template_version,
        terraform_bundle=terraform_bundle,
        yes=yes,
    )


@app.command(rich_help_panel="Deployment")
def destroy(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompts. Does not bypass credential prompts "
        "(admin password still required interactively).",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show the full Terraform output instead of a summary.",
    ),
    purge: bool = typer.Option(
        False,
        "--purge",
        help="Manual provider only: also delete the Postgres data volume. "
        "Ignored for AWS.",
    ),
) -> None:
    """Tear down LabLink infrastructure."""
    cfg = _load_cfg(config)
    if cfg.provider == "manual":
        from lablink_cli.commands.deploy_compose import run_destroy_compose

        run_destroy_compose(cfg, yes=yes, purge=purge)
        return

    from lablink_cli.commands.deploy import run_destroy

    run_destroy(cfg, yes=yes, verbose=verbose)


@client_app.command("launch")
def launch_client(
    num_vms: int = typer.Option(
        ...,
        "--num-vms",
        "-n",
        help="Number of client VMs to launch",
    ),
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show the full Terraform output instead of a summary.",
    ),
) -> None:
    """Launch client VMs via the allocator service.

    AWS provider only: provisions client VMs through Terraform. For
    the manual provider, BYO operators run 'lablink client register' on each
    box instead; this command no-ops with a friendly message.
    """
    from lablink_cli.commands.launch import run_launch

    run_launch(_load_cfg(config), num_vms=num_vms, verbose=verbose)


@app.command(rich_help_panel="Operations")
def status(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
) -> None:
    """Show deployment health and inventory.

    AWS provider: HTTP/DNS/SSL health checks, Terraform state, client
    VM inventory, and a cost estimate. Manual provider: docker-compose
    container status and the allocator's HTTP health endpoint.
    """
    from lablink_cli.commands.status import run_status

    run_status(_load_cfg(config))


@app.command(rich_help_panel="Operations")
def logs(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
) -> None:
    """View allocator and client logs.

    AWS provider: launches the interactive TUI that streams allocator
    and per-VM client logs. Manual provider: tails the local
    'lablink-allocator' docker container's logs (per-VM client logs
    are not centralized; run 'docker logs lablink-client' on each
    BYO box).
    """
    from lablink_cli.commands.logs import run_logs

    run_logs(_load_cfg(config))


@app.command(rich_help_panel="Maintenance")
def cleanup(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be deleted without making changes "
        "(AWS provider only; manual provider's cleanup is non-destructive "
        "until you confirm).",
    ),
) -> None:
    """Remove deployment resources and local state.

    AWS provider: deletes orphaned EC2/IAM/EIP/SG resources and the
    environment-specific Terraform state files. Manual provider: runs
    'docker compose down --volumes' on the local stack and removes
    the compose working directory.
    """
    from lablink_cli.commands.cleanup import run_cleanup

    run_cleanup(
        _load_cfg(config),
        dry_run=dry_run,
    )


@app.command(rich_help_panel="Setup")
def doctor() -> None:
    """Check prerequisites and configuration."""
    from lablink_cli.commands.doctor import run_doctor

    run_doctor()


@client_app.command("register")
def register(
    allocator_url: str = typer.Option(
        ...,
        "--allocator-url",
        help="Base URL of the LabLink allocator "
        "(e.g., https://lablink.example.com).",
    ),
    register_token: str = typer.Option(
        ...,
        "--register-token",
        prompt="Register token",
        hide_input=True,
        envvar="LABLINK_REGISTER_TOKEN",
        help="The bootstrap register_token from the allocator operator "
        "(prompted if omitted; also reads $LABLINK_REGISTER_TOKEN).",
    ),
    hostname: str = typer.Option(
        None, "--hostname",
        help="Override auto-detected hostname.",
    ),
    lan_ip: str = typer.Option(
        None, "--lan-ip",
        help="Override auto-detected LAN IP.",
    ),
    machine_identity: str = typer.Option(
        None, "--machine-identity",
        help="Override auto-detected machine identifier.",
    ),
    gpu_present: bool = typer.Option(
        None, "--gpu-present/--no-gpu-present",
        help="Override auto-detected GPU presence.",
    ),
    gpu_model: str = typer.Option(
        None, "--gpu-model",
        help="Override auto-detected GPU model string.",
    ),
    overlay_hostname: str = typer.Option(
        None, "--overlay-hostname",
        help="Register a mesh-overlay client (e.g. a Run:AI-hosted "
        "workload) under this Tailscale hostname, chosen by you before "
        "the workload exists. Requires --hostname, --machine-identity, "
        "and --tailscale-authkey. No local container is started.",
    ),
    tailscale_authkey: str = typer.Option(
        None, "--tailscale-authkey",
        help="Tailscale auth key the workload will use to join the "
        "tailnet. Required with --overlay-hostname; echoed back in the "
        "printed env block for you to paste into your workload spec.",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="Overwrite an existing ~/.lablink/client.env. Mints a new "
        "client_secret (orphans any running container).",
    ),
    env_file: Path = typer.Option(
        None, "--env-file",
        help="Path to write secrets (default ~/.lablink/client.env).",
    ),
    insecure: bool = typer.Option(
        False, "--insecure",
        help="Skip TLS verification (use when the allocator's "
        "ssl.provider is self_signed).",
    ),
) -> None:
    """Register this BYO box as a manual client and run the client container.

    Always docker-runs the client container after registering. If docker
    is missing, the env file is preserved so the user can install docker
    and re-run with --force.
    """
    from lablink_cli.commands.register import run_register

    run_register(
        allocator_url=allocator_url,
        register_token=register_token,
        hostname=hostname,
        lan_ip=lan_ip,
        machine_identity=machine_identity,
        gpu_present=gpu_present,
        gpu_model=gpu_model,
        force=force,
        env_file=env_file,
        insecure=insecure,
        overlay_hostname=overlay_hostname,
        tailscale_authkey=tailscale_authkey,
    )


@client_app.command("unregister")
def unregister(
    env_file: Path = typer.Option(
        None, "--env-file",
        help="Path to client.env (default ~/.lablink/client.env).",
    ),
    insecure: bool = typer.Option(
        False, "--insecure",
        help="Skip TLS verification for the allocator notify call "
        "(use when the allocator's ssl.provider is self_signed).",
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y",
        help="Skip the confirmation prompt.",
    ),
) -> None:
    """Tear down a registered BYO box.

    Best-effort notifies the allocator, then removes the
    `lablink-client` container and deletes the env file. Idempotent
    — does nothing and exits 0 if there is no env file. Safe to run
    after `lablink destroy` (the allocator will be unreachable, which
    is the expected case).
    """
    from lablink_cli.commands.unregister import run_unregister

    run_unregister(env_file=env_file, insecure=insecure, yes=yes)


@app.command("show-config", rich_help_panel="Maintenance")
def show_config(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
) -> None:
    """View the current LabLink configuration."""
    from rich.console import Console
    from rich.syntax import Syntax

    config_path = Path(config) if config else DEFAULT_CONFIG
    if not config_path.exists():
        typer.echo(
            f"Config not found: {config_path}\n"
            "Run 'lablink configure' first to generate a config."
        )
        raise typer.Exit(1)

    from lablink_cli.config.schema import load_config, validate_config

    raw = config_path.read_text()
    console = Console()
    console.print(
        f"[dim]Config file:[/dim] {config_path}\n"
    )
    console.print(Syntax(raw, "yaml", theme="monokai"))

    cfg = load_config(config_path)
    errors = validate_config(cfg)
    if errors:
        console.print(
            "\n[bold red]Validation errors:[/bold red]"
        )
        for e in errors:
            console.print(f"  [red]*[/red] {e}")
    else:
        console.print("\n[green]Config is valid.[/green]")


def _clear_terraform_cache(console) -> None:
    """Clear the Terraform template cache at ``terraform_source.CACHE_DIR``."""
    import shutil

    from lablink_cli import terraform_source

    cache_dir = terraform_source.CACHE_DIR

    if not cache_dir.exists():
        console.print("[dim]No cache to clear.[/dim]")
        return

    versions = [d.name for d in cache_dir.iterdir() if d.is_dir()]
    if not versions:
        console.print("[dim]Cache is empty.[/dim]")
        return

    for v in sorted(versions):
        console.print(f"  Removing {v}...")
    shutil.rmtree(cache_dir)
    console.print(
        f"[green]Cleared {len(versions)} cached version(s).[/green]"
    )


def _clear_deployments_cache(console, stale_only: bool = False) -> None:
    """Clear the CLI-local deployment metrics cache (issue #317).

    With ``stale_only=True``, delete only records whose ``status`` is
    ``in_progress`` — the leftovers from plan-cancel or Ctrl-C that never
    reached ``success`` / ``failed``. Malformed JSON files are treated as
    stale under ``stale_only`` (they are un-promotable by definition).
    """
    import json

    from lablink_cli import deployment_metrics

    cache_dir = deployment_metrics.DEPLOYMENTS_DIR

    if not cache_dir.exists():
        console.print("[dim]No deployments cache to clear.[/dim]")
        return

    all_records = list(cache_dir.glob("*.json"))
    if not all_records:
        console.print("[dim]Deployments cache is empty.[/dim]")
        return

    if stale_only:
        records = []
        for p in all_records:
            try:
                data = json.loads(p.read_text())
            except json.JSONDecodeError:
                records.append(p)
                continue
            if data.get("status") == "in_progress":
                records.append(p)
        if not records:
            console.print(
                "[dim]No stale (in_progress) deployment records to clear.[/dim]"
            )
            return
    else:
        records = all_records

    for p in records:
        p.unlink()
    label = "stale deployment record" if stale_only else "deployment record"
    suffix = "s" if len(records) != 1 else ""
    console.print(
        f"[green]Cleared {len(records)} {label}{suffix}.[/green]"
    )


@app.command("cache-clear", rich_help_panel="Maintenance")
def cache_clear(
    deployments: bool = typer.Option(
        False,
        "--deployments",
        help=(
            "Clear the local deployment metrics cache "
            "(~/.lablink/deployments/) instead of the Terraform template "
            "cache."
        ),
    ),
    all_caches: bool = typer.Option(
        False,
        "--all",
        help=(
            "Clear all LabLink caches (Terraform templates AND deployment "
            "metrics)."
        ),
    ),
    stale: bool = typer.Option(
        False,
        "--stale",
        help=(
            "With --deployments, delete only in-progress records "
            "(leftovers from plan-cancel or Ctrl-C) instead of the whole "
            "deployments cache. Ignored without --deployments."
        ),
    ),
) -> None:
    """Clear LabLink caches.

    By default clears only the Terraform template cache (backwards-compatible
    with the original command). Use --deployments to clear the CLI-local
    deployment metrics cache, or --all to clear both. Combine --deployments
    with --stale to prune only in-progress records.
    """
    from rich.console import Console

    console = Console()

    if stale and not deployments:
        console.print(
            "[yellow]--stale has no effect without --deployments.[/yellow]"
        )

    if all_caches:
        _clear_terraform_cache(console)
        _clear_deployments_cache(console)
    elif deployments:
        _clear_deployments_cache(console, stale_only=stale)
    else:
        _clear_terraform_cache(console)


@app.command("export-metrics", rich_help_panel="Operations")
def export_metrics(
    output: str = typer.Option(
        None,
        "--output",
        "-o",
        help=(
            "Output file path. With a single source flag, it's the literal "
            "output path. With both flags (or none), it's a base name: "
            "_client / _allocator suffixes are added before the extension. "
            "Default: metrics_client.<fmt> and/or metrics_allocator.<fmt>."
        ),
    ),
    format: str = typer.Option(
        "csv",
        "--format",
        "-f",
        help="Output format: csv or json",
    ),
    include_logs: bool = typer.Option(
        False,
        "--include-logs",
        help="Include cloud_init_logs and docker_logs columns",
    ),
    client: bool = typer.Option(
        False,
        "--client",
        help=(
            "Export per-VM client metrics from the allocator "
            "(default if no flag is given exports both)."
        ),
    ),
    allocator: bool = typer.Option(
        False,
        "--allocator",
        help=(
            "Export per-deploy allocator metrics from the local cache. "
            "Works without a running allocator (e.g. after `lablink destroy`)."
        ),
    ),
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
) -> None:
    """Export deployment metrics to CSV or JSON.

    Pass --client for per-VM metrics from the allocator. Pass --allocator
    for per-deploy metrics from the local cache. With no flag, exports
    both. The --allocator-only path skips the network entirely.
    """
    from lablink_cli.commands.export_metrics import run_export_metrics

    # Skip config load when only --allocator is requested — it doesn't need
    # the config and we want this command to work even after `lablink destroy`.
    needs_cfg = client or not allocator
    cfg = _load_cfg(config) if needs_cfg else None

    run_export_metrics(
        cfg,
        output=output,
        include_logs=include_logs,
        format=format,
        client=client,
        allocator=allocator,
    )


@app.command("stats", rich_help_panel="Operations")
def stats(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
) -> None:
    """Show a cohort session-metrics summary in the terminal."""
    from lablink_cli.commands.stats import run_stats

    run_stats(_load_cfg(config))


def main() -> None:
    app()
