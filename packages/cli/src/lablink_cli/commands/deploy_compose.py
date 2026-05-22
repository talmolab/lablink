"""`lablink deploy/destroy` — manual-provider compose orchestration.

The allocator image is monolithic: it bundles Flask + nginx + an internal
Postgres. This module renders a single-service docker-compose stack
(plus a `.env` and `config.yaml`) into a per-deployment workdir under
`~/.lablink/compose/<deployment_name>/`, runs `docker compose up -d`,
polls the allocator's `/api/health` endpoint, then prints a summary
including the register-token that BYO clients use to join.

Admin/DB credentials live inside the rendered `config.yaml` (mounted at
`/config/config.yaml`), not in env vars — the allocator container does
not read those from the environment.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from importlib import resources
from pathlib import Path

import typer
from rich.console import Console

from lablink_cli.commands.status import check_health_endpoint
from lablink_cli.commands.utils import resolve_admin_credentials
from lablink_cli.config.schema import Config, save_config

DEFAULT_COMPOSE_DIR = Path.home() / ".lablink" / "compose"
DEFAULT_HTTP_PORT = "80"
DEFAULT_HTTPS_PORT = "443"
HEALTH_POLL_TIMEOUT_SECONDS = 300
ALLOCATOR_IMAGE_BASE = "ghcr.io/talmolab/lablink-allocator"
SUPPORTED_SSL_FOR_MANUAL = ("none", "self_signed")
ALLOCATOR_CONTAINER_NAME = "lablink-allocator"

console = Console()


def compose_workdir(cfg: Config) -> Path:
    """Path to the rendered compose working directory for this deployment."""
    name = cfg.deployment_name or "lablink"
    return DEFAULT_COMPOSE_DIR / name


def render_compose_dir(cfg: Config, target: Path) -> None:
    """Render docker-compose.yml + .env + config.yaml into target.

    The allocator image is monolithic (bundles its own Postgres), so the
    compose stack is single-service. The internal Postgres data is
    persisted via a named volume on /var/lib/postgresql. Admin/DB creds
    live in the saved config.yaml (NOT in env vars) — the caller is
    responsible for populating cfg.app.admin_user/admin_password (via
    `resolve_admin_credentials`) before invoking this helper.
    """
    target.mkdir(parents=True, exist_ok=True)

    # 1. Copy the bundled docker-compose template.
    template = resources.files("lablink_cli.templates").joinpath(
        "docker-compose.yml"
    )
    (target / "docker-compose.yml").write_text(template.read_text())

    # 2. Render .env — only the values the compose template substitutes.
    #    No DB or admin creds here: they're inside config.yaml.
    allocator_image = _allocator_image(cfg)
    env_lines = [
        f"ALLOCATOR_IMAGE={allocator_image}",
        f"HTTP_PORT={DEFAULT_HTTP_PORT}",
        f"HTTPS_PORT={DEFAULT_HTTPS_PORT}",
    ]
    env_path = target / ".env"
    env_path.write_text("\n".join(env_lines) + "\n")
    env_path.chmod(0o600)

    # 3. Save config.yaml in the working dir. Mounted into the allocator
    #    container at /config/config.yaml (which matches the container's
    #    CONFIG_DIR default).
    save_config(cfg, target / "config.yaml")


def _allocator_image(cfg: Config) -> str:
    """Construct the full allocator image string from base + image_tag.

    The canonical config exposes only image_tag (e.g.,
    "linux-amd64-latest"); the registry/repo is fixed for now.
    """
    tag = getattr(cfg.allocator, "image_tag", None) or "linux-amd64-latest"
    return f"{ALLOCATOR_IMAGE_BASE}:{tag}"


def run_deploy_compose(
    cfg: Config,
    *,
    yes: bool = False,
    workdir_root: Path | None = None,
) -> None:
    """Bring up the allocator stack via docker-compose.

    Renders the compose working directory (`compose_workdir(cfg)`),
    runs `docker compose up -d`, polls the allocator's `/api/health`
    endpoint until it reports healthy (or times out), and prints a
    summary including the register-token used by BYO clients.

    `yes=True` skips the interactive confirmation prompt.
    `workdir_root` overrides `DEFAULT_COMPOSE_DIR` (used by tests).
    """
    # Preflight: SSL provider must be one the compose template supports.
    if cfg.ssl.provider not in SUPPORTED_SSL_FOR_MANUAL:
        console.print(
            f"[red]Manual provider deploy supports only "
            f"ssl.provider={SUPPORTED_SSL_FOR_MANUAL}, "
            f"got '{cfg.ssl.provider}'.[/red]\n"
            "For public TLS, front the compose stack with your own "
            "reverse proxy (Caddy, nginx, Cloudflare Tunnel)."
        )
        raise SystemExit(1)

    # Preflight: docker on PATH.
    if shutil.which("docker") is None:
        console.print(
            "[red]docker not found on PATH.[/red] "
            "Install Docker Engine + the Compose plugin "
            "(https://docs.docker.com/engine/install/) and re-run."
        )
        raise SystemExit(1)

    # Resolve admin credentials (mirrors AWS deploy.py). The wizard does
    # NOT collect admin user/password — they're resolved here. Write the
    # resolved values back to cfg so render_compose_dir picks them up
    # via cfg.app.admin_user / cfg.app.admin_password.
    admin_user, admin_pw = resolve_admin_credentials(cfg)
    cfg.app.admin_user = admin_user
    cfg.app.admin_password = admin_pw

    target = (workdir_root or DEFAULT_COMPOSE_DIR) / (
        cfg.deployment_name or "lablink"
    )

    if not yes:
        action = "create" if not target.exists() else "update"
        console.print(
            f"About to {action} compose stack in {target}\n"
            f"  provider: manual\n"
            f"  ssl: {cfg.ssl.provider}\n"
            f"  admin user: {admin_user}\n"
        )
        if not typer.confirm("Proceed?", default=True):
            console.print("Aborted.")
            raise SystemExit(1)

    render_compose_dir(cfg, target)
    console.print(f"[green]Rendered {target}[/green]")

    _compose_up(target)
    _health_poll(cfg)
    _print_summary(cfg)


def _compose_up(target: Path) -> None:
    console.print("[bold]docker compose up -d …[/bold]")
    result = subprocess.run(
        ["docker", "compose", "up", "-d"],
        cwd=target,
        check=False,
    )
    if result.returncode != 0:
        console.print("[red]docker compose up failed.[/red]")
        raise SystemExit(result.returncode or 1)


def _health_poll(cfg: Config) -> None:
    """Poll the allocator's /api/health on localhost until healthy."""
    scheme = "https" if cfg.ssl.provider == "self_signed" else "http"
    port = 443 if cfg.ssl.provider == "self_signed" else 80
    base_url = f"{scheme}://localhost:{port}"

    console.print(
        f"[bold]Polling allocator health at {base_url}/api/health "
        f"(up to {HEALTH_POLL_TIMEOUT_SECONDS}s) …[/bold]"
    )
    start = time.monotonic()
    deadline = start + HEALTH_POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        result = check_health_endpoint(base_url)
        if result.get("healthy"):
            elapsed = time.monotonic() - start
            console.print(
                f"[green]Allocator healthy after {elapsed:.0f}s[/green]"
            )
            return
        time.sleep(3)

    console.print(
        "[yellow]Allocator did not become healthy within "
        f"{HEALTH_POLL_TIMEOUT_SECONDS}s.[/yellow]"
    )
    _print_last_log_lines()
    raise SystemExit(1)


def _print_last_log_lines(lines: int = 30) -> None:
    result = subprocess.run(
        ["docker", "logs", "--tail", str(lines), ALLOCATOR_CONTAINER_NAME],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.stdout:
        console.print("[dim]Last allocator log lines:[/dim]")
        console.print(result.stdout)


def _print_summary(cfg: Config) -> None:
    register_token = _extract_register_token()
    scheme = "https" if cfg.ssl.provider == "self_signed" else "http"
    allocator_url = f"{scheme}://localhost"

    console.print("\n[bold green]Deployment complete.[/bold green]")
    console.print(f"  Allocator URL: {allocator_url}")
    console.print(f"  Admin user:    {cfg.app.admin_user}")
    if register_token:
        console.print(f"  Register token: {register_token}")
    else:
        console.print(
            "  Register token: (could not parse from container logs; "
            "fetch with `docker logs lablink-allocator | grep "
            "REGISTER_TOKEN`)"
        )
    console.print(
        "\n[bold]Next step:[/bold] on each BYO box, run\n"
        f"  lablink register --allocator-url {allocator_url} "
        "--register-token <token>"
    )


def _extract_register_token() -> str | None:
    """Parse the register_token from the allocator's startup logs.

    The allocator logs `REGISTER_TOKEN=<token>` at startup (see
    `packages/allocator/src/lablink_allocator_service/main.py` ~line 213).
    Also tolerate the `register_token = "..."` form just in case.
    """
    result = subprocess.run(
        ["docker", "logs", ALLOCATOR_CONTAINER_NAME],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    for pattern in (
        r'REGISTER_TOKEN\s*=\s*"?([A-Za-z0-9_\-]{20,})"?',
        r'register_token\s*=\s*"?([A-Za-z0-9_\-]{20,})"?',
    ):
        m = re.search(pattern, result.stdout)
        if m:
            return m.group(1)
    return None


def run_destroy_compose(
    cfg: Config,
    *,
    yes: bool = False,
    purge: bool = False,
    workdir_root: Path | None = None,
) -> None:
    """Tear down a manual-provider compose stack.

    Default behavior: `docker compose down` (preserves the Postgres
    data volume and the working directory — re-deploying restores the
    DB state).

    With `purge=True`: also runs `--volumes` and removes the working
    directory, wiping all registration history. Destructive.

    `yes=True` skips the interactive confirmation prompt.
    `workdir_root` overrides `DEFAULT_COMPOSE_DIR` (used by tests).
    """
    target = (workdir_root or DEFAULT_COMPOSE_DIR) / (
        cfg.deployment_name or "lablink"
    )

    if not target.exists():
        console.print(
            f"[yellow]No compose stack at {target} — already destroyed.[/yellow]"
        )
        return

    if not yes:
        if purge:
            console.print(
                "[red bold]--purge will DELETE the Postgres data volume "
                "(all registration history, sessions, etc.).[/red bold]"
            )
        confirmation = typer.prompt(
            f"Type 'yes' to tear down compose stack at {target}",
            default="no",
            show_default=False,
        )
        if confirmation.strip().lower() != "yes":
            console.print("Aborted.")
            raise SystemExit(1)

    cmd = ["docker", "compose", "down"]
    if purge:
        cmd.append("--volumes")

    result = subprocess.run(cmd, cwd=target, check=False)
    if result.returncode != 0:
        console.print("[red]docker compose down failed.[/red]")
        raise SystemExit(result.returncode or 1)

    if purge:
        shutil.rmtree(target)
        console.print(f"[green]Removed {target}.[/green]")
    else:
        console.print(
            f"[green]Stack torn down (data preserved in {target}).[/green]"
        )
