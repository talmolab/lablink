"""Rehash admin password in legacy config files."""

from __future__ import annotations

from pathlib import Path
from argon2 import PasswordHasher
import typer
import yaml


def run_rehash(config_path: Path) -> None:
    """Upgrade a legacy config.yaml by hashing the plaintext admin_password.

    Prompts for the admin password, hashes it with argon2, and writes
    admin_password_hash to the config. Removes the plaintext admin_password
    field if present.

    Args:
        config_path: Path to the config.yaml file to update.

    Raises:
        typer.Exit: If the config file is not found or save fails.
    """
    if not config_path.exists():
        typer.echo(
            f"Config file not found: {config_path}\n"
            "Cannot rehash a non-existent config. Run 'lablink configure' first.",
            err=True,
        )
        raise typer.Exit(1)

    # Load the existing config
    try:
        with open(config_path) as f:
            config_data = yaml.safe_load(f)
    except Exception as e:
        typer.echo(
            f"Error reading config file: {e}",
            err=True,
        )
        raise typer.Exit(1)

    if config_data is None:
        config_data = {}

    # Ensure 'app' section exists
    if "app" not in config_data:
        config_data["app"] = {}

    # Prompt for the admin password
    admin_password = typer.prompt(
        "Admin password",
        hide_input=True,
    )

    # Hash the password
    hasher = PasswordHasher()
    password_hash = hasher.hash(admin_password)

    # Update the config
    config_data["app"]["admin_password_hash"] = password_hash

    # Remove the plaintext password if it exists
    config_data["app"].pop("admin_password", None)

    # Write back to file
    try:
        with open(config_path, "w") as f:
            yaml.dump(
                config_data,
                f,
                default_flow_style=False,
                sort_keys=False,
            )
    except Exception as e:
        typer.echo(
            f"Error writing config file: {e}",
            err=True,
        )
        raise typer.Exit(1)

    typer.echo(
        f"[green]✓[/green] Config hashed and saved to {config_path}"
    )
