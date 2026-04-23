"""LabLink CLI entry point."""

from pathlib import Path

import typer

app = typer.Typer(
    name="lablink",
    help="Deploy and manage LabLink teaching lab infrastructure.",
    no_args_is_help=True,
)

DEFAULT_CONFIG = Path.home() / ".lablink" / "config.yaml"


def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import version

        typer.echo(f"lablink-cli {version('lablink-cli')}")
        raise typer.Exit()


@app.callback()
def _root(
    _version: bool = typer.Option(
        False,
        "--version",
        "-v",
        callback=_version_callback,
        is_eager=True,
        help="Show the CLI version and exit.",
    ),
) -> None:
    """Deploy and manage LabLink teaching lab infrastructure."""


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
    """
    from lablink_cli.config.schema import load_config
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

    from lablink_cli.commands.setup import run_setup

    run_setup(load_config(config_path), config_path=config_path)


@app.command(rich_help_panel="Setup")
def setup(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
) -> None:
    """Create S3 + DynamoDB for remote Terraform state.

    Automatically run during 'lablink configure'. Use this
    command to recreate resources if they were deleted.
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
        "Skips checksum verification.",
    ),
    terraform_bundle: str = typer.Option(
        None,
        "--terraform-bundle",
        help="Path to a local template tarball for offline deploys.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompts. Does not bypass credential prompts "
        "(admin/db passwords still required interactively).",
    ),
) -> None:
    """Deploy LabLink infrastructure with Terraform."""
    from lablink_cli.commands.deploy import run_deploy

    run_deploy(
        _load_cfg(config),
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
        "(admin/db passwords still required interactively).",
    ),
) -> None:
    """Tear down LabLink infrastructure."""
    from lablink_cli.commands.deploy import run_destroy

    run_destroy(_load_cfg(config), yes=yes)


@app.command("launch-client", rich_help_panel="Deployment")
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
) -> None:
    """Launch client VMs via the allocator service."""
    from lablink_cli.commands.launch import run_launch

    run_launch(_load_cfg(config), num_vms=num_vms)


@app.command(rich_help_panel="Operations")
def status(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
) -> None:
    """Health checks, Terraform state, and cost estimate."""
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
    """View VM logs in an interactive TUI."""
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
        help="Show what would be deleted without making changes",
    ),
) -> None:
    """Clean up orphaned AWS resources and local state."""
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


def main() -> None:
    app()
