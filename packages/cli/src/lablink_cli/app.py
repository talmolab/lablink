"""LabLink CLI entry point."""

from pathlib import Path

import typer

from lablink_cli.config.schema import load_config

app = typer.Typer(
    name="lablink",
)

client_app = typer.Typer(
    name="client",
    help="Manage the client fleet (register/launch/destroy/unregister).",
)
app.add_typer(client_app, name="client")

DEFAULT_CONFIG = Path.home() / ".lablink" / "config.yaml"

# Where a lablink-template checkout keeps its committed config.
TEMPLATE_CONFIG = Path("lablink-infrastructure") / "config" / "config.yaml"

# The credential fields template mode pins, matching what the template's own
# scripts/configure.sh emits: passwords as sentinels for CI to substitute,
# admin_user as the literal the workflow never touches.
TEMPLATE_CREDENTIALS = {
    ("app", "admin_user"): "admin",
    ("app", "admin_password"): "PLACEHOLDER_ADMIN_PASSWORD",
    ("db", "password"): "PLACEHOLDER_DB_PASSWORD",
}


def _write_template_credentials(path: Path) -> None:
    """Rewrite the wizard's credential defaults to the template's convention.

    lablink-template commits config.yaml and injects the real passwords in
    CI with ``sed s/PLACEHOLDER_<NAME>/.../``. The wizard never collects
    credentials (they're resolved at deploy time on the local path), so it
    writes the ``MISSING`` secret sentinel and the ``db.password`` default —
    neither of which that sed matches. Without this the substitution
    silently does nothing, and the workflow's own ``grep -q PLACEHOLDER_``
    guard still passes, because it only catches placeholders left over, not
    placeholders that were never there. ``admin_user`` gets no sed at all,
    so it has to be a usable value here rather than a sentinel.
    """
    import yaml

    data = yaml.safe_load(path.read_text())
    for (section, key), value in TEMPLATE_CREDENTIALS.items():
        data.setdefault(section, {})[key] = value
    path.write_text(
        yaml.dump(data, default_flow_style=False, sort_keys=False)
    )


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
    template: bool = typer.Option(
        False,
        "--template",
        help="Configure a lablink-template checkout instead of the local "
        "deployment: writes lablink-infrastructure/config/config.yaml with "
        "PLACEHOLDER_* passwords for GitHub Actions to substitute, and "
        "skips AWS state setup (the template's setup.sh does that).",
    ),
) -> None:
    """Create or edit the LabLink configuration.

    Launches a TUI wizard to generate or modify config.yaml,
    then automatically creates the AWS resources needed for
    OpenTofu remote state (S3 bucket + DynamoDB lock table).
    Manual-provider configs skip the AWS setup step.

    With --template, generates the config a lablink-template repo commits
    and deploys via GitHub Actions, so that path gets the same wizard.
    """
    from lablink_cli.tui.wizard import ConfigWizard

    if config:
        config_path = Path(config)
    elif template:
        config_path = TEMPLATE_CONFIG
        # Same guard as the template's own scripts/configure.sh: without it
        # a wrong cwd silently creates a stray lablink-infrastructure/ tree
        # that no workflow will ever read.
        if not TEMPLATE_CONFIG.parent.parent.is_dir():
            typer.echo(
                "--template must be run from the root of a lablink-template "
                f"checkout ({TEMPLATE_CONFIG.parent.parent}/ not found).\n"
                "Pass --config to write somewhere else."
            )
            raise typer.Exit(1)
    else:
        config_path = DEFAULT_CONFIG

    existing = None
    if config_path.exists():
        existing = load_config(config_path)

    wizard = ConfigWizard(existing_config=existing, save_path=config_path)
    wizard.run()

    # After the wizard saves config, run AWS setup automatically
    if not config_path.exists():
        # User quit the wizard without saving
        return

    if template:
        _write_template_credentials(config_path)
        from rich.console import Console

        Console().print(
            f"[dim]Wrote {config_path} with placeholder passwords. "
            "Commit it and push — the Deploy LabLink Infrastructure workflow "
            "substitutes your ADMIN_PASSWORD/DB_PASSWORD secrets.[/dim]"
        )
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
    for OpenTofu remote state. Automatically run during 'lablink
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
        help="Path to a local template tarball for offline deploys. AWS provider only.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip confirmation prompts. Does not bypass credential prompts "
        "(admin password still required interactively).",
    ),
    tailscale_authkey: str = typer.Option(
        None,
        "--tailscale-authkey",
        help="Tailscale auth key for the allocator's own tailnet sidecar. "
        "Needed on the first deploy when manual.connectivity is "
        "'mesh_overlay' and/or manual.participant_exposure is "
        "'tailscale_funnel' (prompted if omitted); optional on redeploys "
        "(the previous value is carried forward). Manual provider only.",
    ),
    cloudflare_tunnel_token: str = typer.Option(
        None,
        "--cloudflare-tunnel-token",
        help="Cloudflare Tunnel token for publishing the allocator at "
        "manual.public_hostname. Needed on the first deploy when "
        "manual.participant_exposure is 'cloudflare_tunnel' (prompted if "
        "omitted); optional on redeploys (the previous value is carried "
        "forward). Supply it again to rotate. Manual provider only.",
    ),
    render_only: bool = typer.Option(
        False,
        "--render-only",
        help="Render the deployment bundle and print a launch sheet "
        "instead of starting containers — for running the allocator "
        "image on an external container platform (Run:AI, Kubernetes) "
        "where no Docker daemon is available. Manual provider only.",
    ),
) -> None:
    """Deploy LabLink infrastructure (AWS OpenTofu or docker-compose)."""
    cfg = _load_cfg(config)

    if render_only and cfg.provider != "manual":
        from rich.console import Console

        Console().print(
            "[red]--render-only is only meaningful with provider: manual "
            f"(this config has provider: {cfg.provider}).[/red]"
        )
        raise typer.Exit(1)

    if cfg.provider == "manual":
        from lablink_cli.commands.deploy_compose import run_deploy_compose

        run_deploy_compose(
            cfg,
            yes=yes,
            tailscale_authkey=tailscale_authkey,
            cloudflare_tunnel_token=cloudflare_tunnel_token,
            render_only=render_only,
        )
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
        help="Show the full OpenTofu output instead of a summary.",
    ),
    keep_data: bool = typer.Option(
        False,
        "--keep-data",
        help="Manual provider only: preserve the Postgres data volume "
        "instead of the default full wipe (registration history, "
        "sessions, etc. survive a subsequent redeploy). Ignored for AWS.",
    ),
) -> None:
    """Tear down LabLink infrastructure."""
    cfg = _load_cfg(config)
    if cfg.provider == "manual":
        from lablink_cli.commands.deploy_compose import run_destroy_compose

        run_destroy_compose(cfg, yes=yes, keep_data=keep_data)
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
        help="Show the full OpenTofu output instead of a summary.",
    ),
) -> None:
    """Launch client VMs via the allocator service.

    AWS provider only: provisions client VMs through OpenTofu. For
    the manual provider, BYO operators run 'lablink client register' on each
    box instead; this command no-ops with a friendly message.
    """
    from lablink_cli.commands.launch import run_launch

    run_launch(_load_cfg(config), num_vms=num_vms, verbose=verbose)


@client_app.command("destroy")
def destroy_client(
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
        help="Show the full OpenTofu output instead of a summary.",
    ),
) -> None:
    """Destroy all client VMs via the allocator service.

    AWS provider only: the allocator runs 'tofu destroy' over its own
    workspace and clears the VM table. Leaves the allocator itself running
    — use 'lablink destroy' to tear down the whole deployment. For the
    manual provider, BYO operators run 'lablink client unregister' on each
    box instead; this command no-ops with a friendly message.
    """
    from lablink_cli.commands.launch import run_client_destroy

    run_client_destroy(_load_cfg(config), yes=yes, verbose=verbose)


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

    AWS provider: HTTP/DNS/SSL health checks, OpenTofu state, client
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
    environment-specific OpenTofu state files. Manual provider: runs
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


@client_app.command("doctor")
def client_doctor() -> None:
    """Check this machine's BYO client (container, log shipper)."""
    from lablink_cli.commands.doctor import run_client_doctor

    run_client_doctor()


@client_app.command("register")
def register(
    allocator_url: str = typer.Option(
        ...,
        "--allocator-url",
        help="Base URL of the LabLink allocator (e.g., https://lablink.example.com).",
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
        None,
        "--hostname",
        help="Override auto-detected hostname.",
    ),
    lan_ip: str = typer.Option(
        None,
        "--lan-ip",
        help="Override auto-detected LAN IP.",
    ),
    machine_identity: str = typer.Option(
        None,
        "--machine-identity",
        help="Override auto-detected machine identifier.",
    ),
    gpu_present: bool = typer.Option(
        None,
        "--gpu-present/--no-gpu-present",
        help="Override auto-detected GPU presence.",
    ),
    gpu_model: str = typer.Option(
        None,
        "--gpu-model",
        help="Override auto-detected GPU model string.",
    ),
    overlay_hostname: str = typer.Option(
        None,
        "--overlay-hostname",
        help="Register a mesh-overlay client (e.g. a Run:AI-hosted "
        "workload) under this Tailscale hostname, chosen by you. "
        "Requires --tailscale-authkey. By default (see --run-locally) "
        "docker-runs the client container on this box now; pass "
        "--no-run-locally to instead print secrets for a separate "
        "workload submission, which also requires --hostname and "
        "--machine-identity.",
    ),
    tailscale_authkey: str = typer.Option(
        None,
        "--tailscale-authkey",
        help="Tailscale auth key the workload will use to join the "
        "tailnet. Required with --overlay-hostname.",
    ),
    run_locally: bool = typer.Option(
        True,
        "--run-locally/--no-run-locally",
        help="With --overlay-hostname: docker-run the client container "
        "on this box now, auto-detecting hostname/machine-identity/GPU "
        "like a real BYO box (default: on). Pass --no-run-locally to "
        "instead just print secrets for pasting into a separate Run:AI "
        "workload submission — for registering ahead of time, from "
        "somewhere other than the workload itself.",
    ),
    tunnel: bool = typer.Option(
        False,
        "--tunnel",
        help="Register a tunnel client: instead of the allocator dialling "
        "this box, the box dials OUT to the allocator and holds one "
        "connection open. For networks that won't carry Tailscale and "
        "boxes that can't accept inbound connections. Takes no arguments — "
        "the allocator mints every value needed. Defaults to "
        "docker-running the client here; pass --no-run-locally to print "
        "secrets for a separate workload submission instead.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing ~/.lablink/client.env. Mints a new "
        "client_secret (orphans any running container).",
    ),
    env_file: Path = typer.Option(
        None,
        "--env-file",
        help="Path to write secrets (default ~/.lablink/client.env).",
    ),
    insecure: bool = typer.Option(
        False,
        "--insecure",
        help="Skip TLS verification (use when the allocator's "
        "ssl.provider is self_signed).",
    ),
) -> None:
    """Register this BYO box as a manual client and run the client container.

    Docker-runs the client container after registering — for a real BYO
    box, or for a mesh-overlay client (--overlay-hostname) with the
    default --run-locally. Pass --overlay-hostname --no-run-locally to
    instead print secrets for a separate Run:AI workload submission. If
    docker is missing, the env file is preserved so the user can install
    docker and re-run with --force.
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
        run_locally=run_locally,
        reverse_tunnel=tunnel,
    )


@client_app.command("unregister")
def unregister(
    env_file: Path = typer.Option(
        None,
        "--env-file",
        help="Path to client.env (default ~/.lablink/client.env).",
    ),
    insecure: bool = typer.Option(
        False,
        "--insecure",
        help="Skip TLS verification for the allocator notify call "
        "(use when the allocator's ssl.provider is self_signed).",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
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


@client_app.command("reset-overlay")
def reset_overlay(
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the confirmation prompt.",
    ),
) -> None:
    """Discard this box's persisted mesh-overlay node identity.

    Only relevant to a mesh-overlay client. `unregister` deliberately
    keeps the identity so that re-registering lands back on the same
    tailnet node under the same name; run this when you want the next
    `register` to join as a brand-new node instead.

    Note that this does not remove the old machine from your tailnet — it
    goes offline still holding its name, so the new node is given a
    numeric suffix until you delete the stale machine in the Tailscale
    admin console. Requires the `lablink-client` container to be gone
    already (docker will not remove an attached volume).
    """
    from lablink_cli.commands.reset_overlay import run_reset_overlay

    run_reset_overlay(yes=yes)


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
    console.print(f"[dim]Config file:[/dim] {config_path}\n")
    console.print(Syntax(raw, "yaml", theme="monokai"))

    cfg = load_config(config_path)
    errors = validate_config(cfg)
    if errors:
        console.print("\n[bold red]Validation errors:[/bold red]")
        for e in errors:
            console.print(f"  [red]*[/red] {e}")
    else:
        console.print("\n[green]Config is valid.[/green]")


def _clear_template_cache(console) -> None:
    """Clear the OpenTofu template cache at ``tofu_source.CACHE_DIR``."""
    import shutil

    from lablink_cli import tofu_source

    cache_dir = tofu_source.CACHE_DIR

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
    console.print(f"[green]Cleared {len(versions)} cached version(s).[/green]")


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
    console.print(f"[green]Cleared {len(records)} {label}{suffix}.[/green]")


@app.command("cache-clear", rich_help_panel="Maintenance")
def cache_clear(
    deployments: bool = typer.Option(
        False,
        "--deployments",
        help=(
            "Clear the local deployment metrics cache "
            "(~/.lablink/deployments/) instead of the template "
            "cache."
        ),
    ),
    all_caches: bool = typer.Option(
        False,
        "--all",
        help=("Clear all LabLink caches (OpenTofu templates AND deployment metrics)."),
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

    By default clears only the template cache (backwards-compatible
    with the original command). Use --deployments to clear the CLI-local
    deployment metrics cache, or --all to clear both. Combine --deployments
    with --stale to prune only in-progress records.
    """
    from rich.console import Console

    console = Console()

    if stale and not deployments:
        console.print("[yellow]--stale has no effect without --deployments.[/yellow]")

    if all_caches:
        _clear_template_cache(console)
        _clear_deployments_cache(console)
    elif deployments:
        _clear_deployments_cache(console, stale_only=stale)
    else:
        _clear_template_cache(console)


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
            "Export per-deploy allocator metrics from the local cache, "
            "scoped to this config's deployment_name. Works without a "
            "running allocator (e.g. after `lablink destroy`); passed "
            "alone it loads no config and exports every deployment."
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
    for per-deploy metrics from the local cache, scoped to this config's
    deployment_name. With no flag, exports both. Passing only --allocator
    skips the network entirely.
    """
    from lablink_cli.commands.export_metrics import run_export_metrics

    # --client cannot work without the config (allocator URL + admin creds),
    # so a missing one is fatal there. --allocator does not need it, but load
    # it when it's there anyway: the config's deployment_name is what scopes
    # the cache export to this deployment instead of dumping every deployment
    # the operator has ever run. Only a machine with no config at all falls
    # through to None (unscoped), which keeps the command usable after a wipe.
    config_path = Path(config) if config else DEFAULT_CONFIG
    cfg = (
        _load_cfg(config)
        if client or not allocator or config_path.exists()
        else None
    )

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
