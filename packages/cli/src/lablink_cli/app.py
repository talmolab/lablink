"""LabLink CLI entry point."""

from pathlib import Path

import typer

app = typer.Typer(
    name="lablink",
    help="Deploy and manage LabLink teaching lab infrastructure.",
    no_args_is_help=True,
)

DEFAULT_CONFIG = Path.home() / ".lablink" / "config.yaml"


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


@app.command()
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


@app.command()
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


@app.command()
def deploy(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
) -> None:
    """Deploy LabLink infrastructure with Terraform."""
    from lablink_cli.commands.deploy import run_deploy

    run_deploy(_load_cfg(config))


@app.command()
def destroy(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
) -> None:
    """Tear down LabLink infrastructure."""
    from lablink_cli.commands.deploy import run_destroy

    run_destroy(_load_cfg(config))


@app.command("launch-client")
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


@app.command()
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


@app.command()
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
    include_remote: bool = typer.Option(
        False,
        "--include-remote",
        help="Also delete S3 bucket and DynamoDB lock table",
    ),
) -> None:
    """Clean up orphaned AWS resources and local state."""
    from lablink_cli.commands.cleanup import run_cleanup

    run_cleanup(
        _load_cfg(config),
        dry_run=dry_run,
        include_remote=include_remote,
    )


@app.command()
def doctor() -> None:
    """Check prerequisites and configuration."""
    from lablink_cli.commands.doctor import run_doctor

    run_doctor()


@app.command("show-config")
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


def main() -> None:
    app()
