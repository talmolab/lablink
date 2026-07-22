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
import socket
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
HEALTH_POLL_TIMEOUT_SECONDS = 300
ALLOCATOR_IMAGE_BASE = "ghcr.io/talmolab/lablink-allocator-image"
# Only ssl=none is supported by the manual-provider compose stack today:
# the allocator image has no TLS terminator (Caddy is part of the AWS
# infrastructure, not the container). For public TLS, operators front the
# stack with their own reverse proxy.
SUPPORTED_SSL_FOR_MANUAL = ("none",)
ALLOCATOR_CONTAINER_NAME = "lablink-allocator"

console = Console()


def compose_workdir(cfg: Config, root: Path | None = None) -> Path:
    """Path to the rendered compose working directory for this deployment.

    `root` overrides `DEFAULT_COMPOSE_DIR` (used by tests via `workdir_root`).
    """
    name = cfg.deployment_name or "lablink"
    return (root or DEFAULT_COMPOSE_DIR) / name


def _read_env_value(env_path: Path, key: str) -> str | None:
    """Read a single KEY=value line from an existing .env file.

    Used to carry TS_AUTHKEY forward across redeploys without requiring
    the admin to re-supply --tailscale-authkey every time — tailscaled's
    own state (the tailscale_state volume) is what actually matters after
    the first join, but the sidecar's compose environment still needs
    *some* value on every render.
    """
    if not env_path.exists():
        return None
    prefix = f"{key}="
    for line in env_path.read_text().splitlines():
        if line.startswith(prefix):
            return line[len(prefix):]
    return None


def render_compose_dir(
    cfg: Config, target: Path, *, tailscale_authkey: str | None = None
) -> None:
    """Render docker-compose.yml + .env + config.yaml into target.

    The allocator image is monolithic (bundles its own Postgres), so the
    compose stack is single-service — plus a `tailscale` sidecar service
    whenever a tailnet join is needed for either of two independent
    reasons: `cfg.manual.connectivity == "mesh_overlay"` (network_mode:
    service:allocator, so the allocator's own nginx can route to a
    mesh-overlay client's Tailscale hostname) or
    `cfg.manual.participant_exposure == "tailscale_funnel"` (so the
    allocator can publish itself to participants via Funnel). Both reuse
    the exact same sidecar — it doesn't care which reason applies. The
    internal Postgres data is persisted via a named volume on
    /var/lib/postgresql. Admin/DB creds live in the saved config.yaml
    (NOT in env vars) — the caller is responsible for populating
    cfg.app.admin_user/admin_password (via `resolve_admin_credentials`)
    before invoking this helper.

    `tailscale_authkey` is only meaningful when the sidecar is needed. It
    is not persisted in config.yaml (unlike admin/DB creds) — only into
    this deployment's .env, and only for as long as the sidecar needs it
    to join for the first time.
    """
    target.mkdir(parents=True, exist_ok=True)
    needs_sidecar = (
        cfg.manual.connectivity == "mesh_overlay"
        or cfg.manual.participant_exposure == "tailscale_funnel"
    )

    # 1. Copy the bundled docker-compose template — the sidecar variant
    #    adds the Tailscale sidecar; otherwise identical.
    template_name = (
        "docker-compose-mesh-overlay.yml" if needs_sidecar else "docker-compose.yml"
    )
    template = resources.files("lablink_cli.templates").joinpath(template_name)
    (target / "docker-compose.yml").write_text(template.read_text())

    # 2. Render .env — only the values the compose template substitutes.
    #    No DB or admin creds here: they're inside config.yaml. Read the
    #    OLD .env (if any) before overwriting it, so a redeploy that
    #    omits --tailscale-authkey carries the previous value forward
    #    instead of blanking out an already-joined sidecar's key.
    env_path = target / ".env"
    previous_authkey = _read_env_value(env_path, "TS_AUTHKEY")

    allocator_image = _allocator_image(cfg)
    env_lines = [
        f"ALLOCATOR_IMAGE={allocator_image}",
        f"HTTP_PORT={DEFAULT_HTTP_PORT}",
    ]
    if needs_sidecar:
        resolved_authkey = tailscale_authkey or previous_authkey or ""
        env_lines.append(f"TS_AUTHKEY={resolved_authkey}")
        env_lines.append(
            f"TAILSCALE_HOSTNAME=lablink-allocator-{cfg.deployment_name or 'lablink'}"
        )
    env_path.write_text("\n".join(env_lines) + "\n")
    env_path.chmod(0o600)

    # 3. Save config.yaml in the working dir. Mounted into the allocator
    #    container at /config/config.yaml (which matches the container's
    #    CONFIG_DIR default).
    save_config(cfg, target / "config.yaml")

    # 4. Stage the custom startup script. Mirrors deploy.py:99-117 for
    #    the AWS path: ~/.lablink/custom-startup.sh wins (CLI override),
    #    else cfg.startup_script.path on the operator's filesystem. The
    #    file is always materialized (empty when disabled or absent) so
    #    the docker-compose bind mount resolves on every deploy; the
    #    allocator's registration handler only forwards it to clients
    #    when cfg.startup_script.enabled is true AND the file is non-
    #    empty.
    startup_target = target / "custom-startup.sh"
    if cfg.startup_script.enabled and cfg.startup_script.path:
        user_script = Path.home() / ".lablink" / "custom-startup.sh"
        if user_script.exists():
            src_startup = user_script
        else:
            src_startup = Path(cfg.startup_script.path)
        if src_startup.exists():
            shutil.copy2(src_startup, startup_target)
        else:
            console.print(
                f"[yellow]startup_script.enabled=true but {src_startup} "
                "not found — continuing without it.[/yellow]"
            )
            startup_target.touch()
    else:
        startup_target.touch()


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
    tailscale_authkey: str | None = None,
) -> None:
    """Bring up the allocator stack via docker-compose.

    Renders the compose working directory (`compose_workdir(cfg)`),
    runs `docker compose up -d`, polls the allocator's `/api/health`
    endpoint until it reports healthy (or times out), and prints a
    summary including the register-token used by BYO clients.

    `yes=True` skips the interactive confirmation prompt.
    `workdir_root` overrides `DEFAULT_COMPOSE_DIR` (used by tests).
    `tailscale_authkey` is required when `cfg.manual.connectivity ==
    "mesh_overlay"` unless a value is already on record in this
    deployment's existing `.env` (the sidecar has nothing to join with
    otherwise) — carried forward on ordinary mesh-overlay redeploys by
    `render_compose_dir`.
    """
    target = compose_workdir(cfg, workdir_root)

    needs_sidecar = (
        cfg.manual.connectivity == "mesh_overlay"
        or cfg.manual.participant_exposure == "tailscale_funnel"
    )
    if needs_sidecar:
        # Checking ".env exists" alone (i.e. "is this a redeploy") isn't
        # enough: a redeploy that *switches* to needing the sidecar has
        # an existing .env, but that .env has no TS_AUTHKEY line to carry
        # forward. Read the actual prior value (if any) so that case
        # still requires --tailscale-authkey instead of silently
        # rendering an empty key.
        previous_authkey = _read_env_value(target / ".env", "TS_AUTHKEY")
        if not tailscale_authkey and not previous_authkey:
            console.print(
                "[red]A Tailscale sidecar is needed (manual.connectivity "
                "is 'mesh_overlay' and/or manual.participant_exposure is "
                "'tailscale_funnel') but no --tailscale-authkey was given, "
                "and no previous value is on record for this "
                "deployment.[/red]\n"
                "Generate an authkey from your Tailscale admin console "
                "and re-run with --tailscale-authkey <key>."
            )
            raise SystemExit(1)
    # Preflight: SSL provider must be one the compose template supports.
    # The allocator image has no TLS terminator, so only ssl=none works
    # out of the box. Operators who need TLS run their own reverse proxy
    # in front of the compose stack.
    if cfg.ssl.provider not in SUPPORTED_SSL_FOR_MANUAL:
        console.print(
            f"[red]Manual provider deploy supports only "
            f"ssl.provider='none' (got '{cfg.ssl.provider}').[/red]\n"
            "The allocator image has no TLS terminator; for public TLS, "
            "front the compose stack with your own reverse proxy "
            "(Caddy, nginx, Cloudflare Tunnel)."
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

    # Preflight: a Funnel-exposed allocator is scanned by bots within
    # minutes of publication (empirically confirmed 2026-07-22) — refuse
    # to ship a weak/example admin password once that's the case. Placed
    # after resolve_admin_credentials so a value resolved interactively
    # is what actually gets checked, not whatever (possibly empty) value
    # cfg.app.admin_password held before resolution.
    if cfg.manual.participant_exposure == "tailscale_funnel":
        from lablink_allocator_service.validate_config import is_weak_admin_password

        if is_weak_admin_password(admin_pw):
            console.print(
                "[red]manual.participant_exposure is 'tailscale_funnel' "
                "but the resolved admin password is empty, a known "
                "example value, or shorter than 12 characters.[/red]\n"
                "A Funnel-exposed allocator is reachable from the public "
                "internet and gets scanned within minutes — set a strong "
                "admin_password (12+ characters, not a common default) "
                "before deploying."
            )
            raise SystemExit(1)

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

    render_compose_dir(cfg, target, tailscale_authkey=tailscale_authkey)
    console.print(f"[green]Rendered {target}[/green]")

    _compose_up(target)
    _health_poll()
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


def _health_poll() -> None:
    """Poll the allocator's /api/health on localhost until healthy."""
    # Manual provider is HTTP-only; the host port comes from the rendered
    # .env, which defaults to DEFAULT_HTTP_PORT.
    base_url = f"http://localhost:{DEFAULT_HTTP_PORT}"

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
    # Manual provider is HTTP-only; preflight rejects anything else.
    local_url = "http://localhost"
    lan_ip = _detect_lan_ip()
    lan_url = f"http://{lan_ip}" if lan_ip else None
    # BYO clients run on different boxes, so the register command needs
    # an address those boxes can route to — localhost is only useful for
    # self-registration on the operator's host. Prefer the LAN URL when
    # we could detect one.
    register_url = lan_url or local_url

    console.print("\n[bold green]Deployment complete.[/bold green]")
    console.print(f"  Allocator URL (local): {local_url}")
    if lan_url:
        console.print(f"  Allocator URL (LAN):   {lan_url}")
    else:
        # Be loud about *why* we couldn't pin a LAN address — operators
        # who are routing through Tailscale/VPN/etc. need to know they
        # have to substitute the right hostname themselves.
        console.print(
            "  Allocator URL (LAN):   (no LAN IP detected — pass the "
            "operator host's reachable address manually)"
        )
    console.print(f"  Admin user:            {cfg.app.admin_user}")
    if register_token:
        console.print(f"  Register token:        {register_token}")
    else:
        # The allocator logs to stderr (Python `logging` default), so
        # the recovery command MUST redirect stderr (`2>&1`) before the
        # pipe — otherwise grep sees only the container's stdout and
        # the user gets an empty result, same root cause as the bug this
        # path is recovering from.
        # soft_wrap=True keeps the docker-logs hint on a single line so
        # the suggested command is not split mid-pipe in narrow terminals.
        console.print(
            "  Register token:        (could not parse from container "
            "logs; fetch with `docker logs lablink-allocator 2>&1 | "
            "grep REGISTER_TOKEN`)",
            soft_wrap=True,
            highlight=False,
        )

    # Print a copy-paste-ready command using the LAN URL when available
    # (clients registering over the LAN can't reach localhost). The
    # token-bearing line uses soft_wrap=True so narrow terminals don't
    # insert a hard newline mid-command — that would break the
    # operator's copy-paste.
    mesh_overlay = cfg.manual.connectivity == "mesh_overlay"
    if mesh_overlay:
        # A mesh-overlay client (e.g. a Run:AI-hosted workload) isn't on
        # the allocator's LAN at all — "on each BYO box on the same LAN"
        # is wrong here. --run-locally defaults to on, so hostname/
        # machine-identity/GPU are auto-detected same as real BYO; only
        # --overlay-hostname/--tailscale-authkey are required.
        console.print(
            "\n[bold]Next step:[/bold] for each mesh-overlay client "
            "(e.g. a Run:AI-hosted workload), open a terminal inside "
            "that workload and run (hostname/machine-identity/GPU are "
            "auto-detected):"
        )
        register_cmd = (
            f"  lablink client register --allocator-url {register_url} "
            f"--register-token {register_token or '<token>'} "
            "--overlay-hostname <name> --tailscale-authkey <key>"
        )
    else:
        console.print(
            "\n[bold]Next step:[/bold] on each BYO box on the same LAN, run"
        )
        register_cmd = (
            f"  lablink client register --allocator-url {register_url} "
            f"--register-token {register_token or '<token>'}"
        )
    console.print(register_cmd, soft_wrap=True, highlight=False)
    if mesh_overlay:
        console.print(
            "  [dim]Registering ahead of time from elsewhere instead? "
            "Add --no-run-locally to print secrets for your own "
            "workload submission instead of running here, along with "
            "--hostname/--machine-identity.[/dim]"
        )
    if not lan_url:
        # If we fell back to localhost, the printed command only works
        # for a BYO client *on the operator host*. Call that out so the
        # operator doesn't blindly hand it to a remote teammate.
        console.print(
            "  [yellow]Note:[/yellow] the URL above is localhost — only "
            "valid for a BYO client running on this same machine. For "
            "clients on another box, substitute this host's LAN IP / "
            "hostname.",
            soft_wrap=True,
            highlight=False,
        )


def _detect_lan_ip() -> str | None:
    """Best-effort: the IPv4 address another host on the operator's LAN
    would use to reach this machine. Returns ``None`` if we can't pick
    one (no default route, only loopback configured, …).

    Uses the kernel routing-table trick: open a UDP socket and call
    ``connect()`` to a public IP. No packets are sent (UDP is
    connectionless), but the kernel resolves the route and binds the
    socket's local address — which we then read back via
    ``getsockname()``. Works offline as long as a default route exists.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 8.8.8.8 is a well-known recipe target — we only need the
        # kernel to pick *an* outbound interface, nothing is transmitted.
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()

    # A loopback or unspecified address means the operator's box doesn't
    # have a usable LAN interface; treat that as "no LAN IP".
    if not ip or ip.startswith("127.") or ip == "0.0.0.0":
        return None
    return ip


def _extract_register_token() -> str | None:
    """Parse the register_token from the allocator's startup logs.

    The allocator logs `REGISTER_TOKEN=<token>` at startup (see
    `packages/allocator/src/lablink_allocator_service/main.py` ~line 213).
    Also tolerate the `register_token = "..."` form just in case.

    Python's `logging.basicConfig` writes to stderr, and `docker logs`
    preserves the container's stdout/stderr split — so we MUST merge
    both streams here (via `stderr=subprocess.STDOUT`), otherwise the
    token line is captured into `.stderr` and the search of `.stdout`
    silently misses it.
    """
    result = subprocess.run(
        ["docker", "logs", ALLOCATOR_CONTAINER_NAME],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
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
    keep_data: bool = False,
    workdir_root: Path | None = None,
) -> None:
    """Tear down a manual-provider compose stack.

    Default behavior: wipes everything — `docker compose down --volumes`
    (deletes the Postgres data volume: all registration history,
    sessions, etc.) plus the working directory. A subsequent
    `lablink deploy` with the same deployment_name then starts from a
    genuinely empty database, matching what "destroy" means for every
    other provider — previously the default silently preserved the old
    volume, so a "fresh" redeploy kept showing every client registered
    under a prior deployment.

    With `keep_data=True`: only `docker compose down` (no `--volumes`),
    and the working directory is left in place — re-deploying with the
    same deployment_name restores the previous DB state instead of
    starting fresh. Opt into this only if that's specifically what you
    want (e.g. a deliberate maintenance restart, not a real teardown).

    `yes=True` skips the interactive confirmation prompt.
    `workdir_root` overrides `DEFAULT_COMPOSE_DIR` (used by tests).
    """
    target = compose_workdir(cfg, workdir_root)

    if not target.exists():
        console.print(
            f"[yellow]No compose stack at {target} — already destroyed.[/yellow]"
        )
        return

    if not yes:
        if not keep_data:
            console.print(
                "[red bold]This will DELETE the Postgres data volume "
                "(all registration history, sessions, etc.). Pass "
                "--keep-data to preserve it instead.[/red bold]"
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
    if not keep_data:
        cmd.append("--volumes")

    result = subprocess.run(cmd, cwd=target, check=False)
    if result.returncode != 0:
        console.print("[red]docker compose down failed.[/red]")
        raise SystemExit(result.returncode or 1)

    if not keep_data:
        shutil.rmtree(target)
        console.print(f"[green]Removed {target}.[/green]")
    else:
        console.print(
            f"[green]Stack torn down (data preserved in {target}).[/green]"
        )

    console.print(
        "\n[bold]Reminder:[/bold] each BYO client box still has "
        "`lablink-client` running.\n"
        "Run [bold]lablink client unregister[/bold] on each box to clean up."
    )
