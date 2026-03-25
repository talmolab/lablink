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

    Launches a TUI wizard to generate or modify config.yaml.
    If a config already exists, it is loaded for editing.
    """
    from lablink_cli.config.schema import load_config
    from lablink_cli.tui.wizard import ConfigWizard

    config_path = Path(config) if config else DEFAULT_CONFIG

    existing = None
    if config_path.exists():
        existing = load_config(config_path)

    wizard = ConfigWizard(existing_config=existing)
    wizard.run()


@app.command()
def setup(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
) -> None:
    """Create S3 + DynamoDB for remote Terraform state (optional).

    Only needed if you want shared state across machines.
    By default, lablink deploy uses local state and this step
    is not required.
    """
    from lablink_cli.commands.setup import run_setup

    run_setup(_load_cfg(config))


@app.command()
def deploy(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
    remote_state: bool = typer.Option(
        False,
        "--remote-state",
        help="Use S3 backend (requires 'lablink setup' first)",
    ),
) -> None:
    """Deploy LabLink infrastructure with Terraform."""
    from lablink_cli.commands.deploy import run_deploy

    run_deploy(_load_cfg(config), remote_state=remote_state)


@app.command()
def destroy(
    config: str = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to config.yaml (default: ~/.lablink/config.yaml)",
    ),
    remote_state: bool = typer.Option(
        False,
        "--remote-state",
        help="Use S3 backend for state",
    ),
) -> None:
    """Tear down LabLink infrastructure."""
    from lablink_cli.commands.deploy import run_destroy

    run_destroy(_load_cfg(config), remote_state=remote_state)


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
def config(
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

    raw = config_path.read_text()
    console = Console()
    console.print(
        f"[dim]Config file:[/dim] {config_path}\n"
    )
    console.print(Syntax(raw, "yaml", theme="monokai"))


def main() -> None:
    app()
