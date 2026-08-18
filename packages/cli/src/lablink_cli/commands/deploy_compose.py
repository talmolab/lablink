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
import time
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path

import typer
from rich.console import Console

from lablink_cli.commands.status import check_health_endpoint
from lablink_cli.commands.utils import resolve_admin_credentials
from lablink_cli.config.schema import Config, save_config
from lablink_cli.deployment_metrics import (
    DeploymentMetrics,
    cache_path_for,
    phase_timer,
    write_metrics,
)
from lablink_cli.docker import Docker, DockerUnavailable, default_docker
from lablink_cli.manual import (
    CANONICAL_URL_FILENAME,
    DEFAULT_COMPOSE_DIR,  # noqa: F401 — re-exported for callers/tests
    DEFAULT_HTTP_PORT,
    workdir as compose_workdir,
)

HEALTH_POLL_TIMEOUT_SECONDS = 300
ALLOCATOR_IMAGE_BASE = "ghcr.io/talmolab/lablink-allocator-image"
# Only ssl=none is supported by the manual-provider compose stack today:
# the allocator image has no TLS terminator (Caddy is part of the AWS
# infrastructure, not the container). For public TLS, operators front the
# stack with their own reverse proxy.
SUPPORTED_SSL_FOR_MANUAL = ("none",)
ALLOCATOR_CONTAINER_NAME = "lablink-allocator"
TAILSCALE_SIDECAR_CONTAINER_NAME = "lablink-allocator-tailscale"
# The allocator's own nginx port inside the sidecar's shared network
# namespace — same target the manual `tailscale funnel 5000` spike used.
ALLOCATOR_INTERNAL_PORT = 5000
# Exact substring from `tailscale funnel`'s own output when the tailnet
# hasn't granted the Funnel ACL yet (verified live, 2026-07-22 spike).
FUNNEL_ACL_NOT_GRANTED_MARKER = "Funnel is not enabled on your tailnet"
FUNNEL_ENABLE_MAX_ATTEMPTS = 5
FUNNEL_ENABLE_RETRY_DELAY_SECONDS = 2
# Budget for the public-hostname check to survive cloudflared's own startup
# (see _verify_public_hostname). Live runs registered the first edge
# connection ~1s after `docker compose up` returned and served traffic within
# a few seconds; 6 tries 5s apart leaves ~25s of headroom over that.
PUBLIC_HOSTNAME_MAX_ATTEMPTS = 6
PUBLIC_HOSTNAME_RETRY_DELAY_SECONDS = 5
console = Console()


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
            return line[len(prefix) :]
    return None


def _needs_tailscale_sidecar(cfg: Config) -> bool:
    """True if a tailnet join is needed for either of two independent
    reasons: reaching mesh-overlay clients, or publishing the allocator
    itself to participants via Funnel. Both reuse the same sidecar."""
    return (
        cfg.manual.connectivity == "mesh_overlay"
        or cfg.manual.participant_exposure == "tailscale_funnel"
    )


def _tailscale_state_volume_exists(target: Path, *, docker: Docker) -> bool:
    """True if this deployment's `tailscale_state` volume already exists.

    Default `lablink destroy` preserves this volume (it carries the
    sidecar's Tailscale node identity, not "data") but removes the whole
    working directory, including the `.env` that would otherwise carry
    TS_AUTHKEY forward. Without this check, a redeploy after such a
    destroy would demand a fresh --tailscale-authkey purely because
    there's no .env to read one from — even though the sidecar's identity
    is already authenticated and sitting in this preserved volume, and
    containerboot skips the `tailscale up --authkey` step when valid
    state is already present. Guessed the same way as
    `_pgdata_volume_name`'s fallback (verified via `docker volume
    inspect`, safe because target.name is regex-constrained to Compose's
    own project-name character set).
    """
    return docker.volume_exists(f"{target.name}_tailscale_state")


def render_compose_dir(
    cfg: Config,
    target: Path,
    *,
    tailscale_authkey: str | None = None,
    cloudflare_tunnel_token: str | None = None,
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
    the exact same sidecar — it doesn't care which reason applies, which
    is why it ships as one `docker-compose.override.yml` layered over the
    single base stack rather than as a second full copy of it. The
    internal Postgres data is persisted via a named volume on
    /var/lib/postgresql. Admin/DB creds live in the saved config.yaml
    (NOT in env vars) — the caller is responsible for populating
    cfg.app.admin_user/admin_password (via `resolve_admin_credentials`)
    before invoking this helper.

    `tailscale_authkey` is only meaningful when the sidecar is needed. It
    is not persisted in config.yaml (unlike admin/DB creds) — only into
    this deployment's .env, and only for as long as the sidecar needs it
    to join for the first time.

    `cloudflare_tunnel_token` is only meaningful when
    `cfg.manual.participant_exposure == "cloudflare_tunnel"`, and follows
    the same rules as `tailscale_authkey`: .env only, carried forward on a
    redeploy that omits it, overridden when supplied again (rotation).
    """
    target.mkdir(parents=True, exist_ok=True)
    needs_sidecar = _needs_tailscale_sidecar(cfg)

    # 1. Copy the bundled compose templates. The base stack is always the
    #    same file; the Tailscale sidecar arrives as Compose's own
    #    auto-loaded `docker-compose.override.yml`, so no `docker compose`
    #    call site needs `-f` flags. Delete a stale override when the
    #    sidecar is no longer needed — Compose would otherwise keep
    #    merging it and silently rejoin the tailnet on the next redeploy.
    templates = resources.files("lablink_cli.templates")
    (target / "docker-compose.yml").write_text(
        templates.joinpath("docker-compose.yml").read_text()
    )
    override_path = target / "docker-compose.override.yml"
    if needs_sidecar:
        override_path.write_text(
            templates.joinpath("docker-compose.tailscale-override.yml").read_text()
        )
    else:
        override_path.unlink(missing_ok=True)

    # 2. Render .env — only the values the compose template substitutes.
    #    No DB or admin creds here: they're inside config.yaml. Read the
    #    OLD .env (if any) before overwriting it, so a redeploy that
    #    omits --tailscale-authkey carries the previous value forward
    #    instead of blanking out an already-joined sidecar's key.
    env_path = target / ".env"
    previous_authkey = _read_env_value(env_path, "TS_AUTHKEY")
    previous_cf_token = _read_env_value(env_path, "CLOUDFLARE_TUNNEL_TOKEN")

    allocator_image = _allocator_image(cfg)
    env_lines = [
        f"ALLOCATOR_IMAGE={allocator_image}",
        f"HTTP_PORT={DEFAULT_HTTP_PORT}",
        # Always declared: the compose templates substitute it
        # unconditionally, and an unset variable makes `docker compose up`
        # warn on every deploy.
        f"PARTICIPANT_EXPOSURE={cfg.manual.participant_exposure}",
    ]
    if cfg.manual.participant_exposure == "cloudflare_tunnel":
        # Same carry-forward rule as TS_AUTHKEY: a redeploy that omits the
        # flag keeps the working token, while an explicitly supplied one
        # wins (that is the rotation path).
        env_lines.append(
            f"CLOUDFLARE_TUNNEL_TOKEN="
            f"{cloudflare_tunnel_token or previous_cf_token or ''}"
        )
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
    # 4b. Stage the canonical-URL file. Always materialized (empty when the
    #     deployment isn't Funnel-exposed) so the compose bind mount resolves
    #     on every deploy — same reason custom-startup.sh below always exists.
    #     _enable_funnel fills it in after `compose up`, since Funnel can only
    #     be turned on once the sidecar is running. An existing value is
    #     preserved across a redeploy that stays Funnel-exposed, so the window
    #     between container start and _enable_funnel doesn't fall back to
    #     request.host_url; a deployment that turns exposure off is cleared,
    #     which is what stops a stale public URL being handed to clients.
    canonical_target = target / CANONICAL_URL_FILENAME
    if cfg.manual.participant_exposure == "tailscale_funnel":
        previous_url = (
            canonical_target.read_text() if canonical_target.exists() else ""
        )
        canonical_target.write_text(previous_url)
    elif cfg.manual.participant_exposure == "cloudflare_tunnel":
        # Known up front — the admin typed it. No after-the-fact write, and
        # no window where the allocator reports the wrong URL.
        canonical_target.write_text(f"https://{cfg.manual.public_hostname}")
    else:
        canonical_target.write_text("")

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
    cloudflare_tunnel_token: str | None = None,
    docker: Docker | None = None,
) -> None:
    """Bring up the allocator stack via docker-compose.

    Renders the compose working directory (`compose_workdir(cfg)`),
    runs `docker compose up -d`, polls the allocator's `/api/health`
    endpoint until it reports healthy (or times out), and prints a
    summary including the register-token used by BYO clients.

    `yes=True` skips the interactive confirmation prompt.
    `workdir_root` overrides `DEFAULT_COMPOSE_DIR` (used by tests).
    `tailscale_authkey` is required when a tailnet join is needed for
    either `cfg.manual.connectivity == "mesh_overlay"` or
    `cfg.manual.participant_exposure == "tailscale_funnel"`, unless a
    value is already on record in this deployment's existing `.env`
    (carried forward on ordinary redeploys by `render_compose_dir`) or
    the sidecar already has a valid, authenticated identity sitting in
    its preserved `tailscale_state` volume (e.g. after a default
    `lablink destroy`, which wipes the working directory — including
    `.env` — but keeps that volume specifically so this doesn't force a
    needless re-auth).
    `cloudflare_tunnel_token` is required when
    `cfg.manual.participant_exposure == "cloudflare_tunnel"`, unless a
    value is already on record in this deployment's existing `.env`. There
    is no state-volume equivalent here: the tunnel's identity lives in
    Cloudflare's account, and the token is the only local copy.
    """
    docker = docker or default_docker()
    target = compose_workdir(cfg, workdir_root)

    needs_sidecar = _needs_tailscale_sidecar(cfg)
    if needs_sidecar:
        # Checking ".env exists" alone (i.e. "is this a redeploy") isn't
        # enough: a redeploy that *switches* to needing the sidecar has
        # an existing .env, but that .env has no TS_AUTHKEY line to carry
        # forward. Read the actual prior value (if any) so that case
        # still requires --tailscale-authkey instead of silently
        # rendering an empty key.
        previous_authkey = _read_env_value(target / ".env", "TS_AUTHKEY")
        if (
            not tailscale_authkey
            and not previous_authkey
            and not _tailscale_state_volume_exists(target, docker=docker)
        ):
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

    # Preflight: cloudflare_tunnel needs a hostname and a token. The
    # hostname is also checked by get_config_errors(), but `lablink deploy`
    # never calls that validator for the manual provider — this is the
    # actual enforcement point for a hand-edited config.yaml. Modeled on
    # the TS_AUTHKEY check above, minus the state-volume clause: there is
    # no volume here, so "on record in .env" is the whole condition.
    if cfg.manual.participant_exposure == "cloudflare_tunnel":
        if not cfg.manual.public_hostname:
            console.print(
                "[red]manual.participant_exposure is 'cloudflare_tunnel' but "
                "manual.public_hostname is empty.[/red]\n"
                "Set it to the hostname you configured as the tunnel's "
                "public hostname in Cloudflare (e.g. lab.smithlab.org)."
            )
            raise SystemExit(1)
        from lablink_allocator_service.validate_config import (
            PUBLIC_HOSTNAME_HINT,
            is_valid_public_hostname,
        )

        # The value is interpolated into "https://{host}" for the canonical-URL
        # file clients are handed, and canonical_base_url accepts anything that
        # merely startswith("https://") — so a pasted scheme yields
        # "https://https://host" that fails silently rather than loudly.
        if not is_valid_public_hostname(cfg.manual.public_hostname):
            console.print(
                "[red]manual.public_hostname is not a bare hostname.[/red]\n"
                f"It {PUBLIC_HOSTNAME_HINT}.",
                highlight=False,
            )
            console.print(f"  got: {cfg.manual.public_hostname!r}", highlight=False)
            raise SystemExit(1)
        previous_cf_token = _read_env_value(target / ".env", "CLOUDFLARE_TUNNEL_TOKEN")
        if not cloudflare_tunnel_token and not previous_cf_token:
            console.print(
                "[red]manual.participant_exposure is 'cloudflare_tunnel' but "
                "no --cloudflare-tunnel-token was given, and no previous "
                "value is on record for this deployment.[/red]\n"
                "Create a tunnel in Cloudflare's Zero Trust dashboard "
                "(Networks > Tunnels), copy the token from its Docker "
                "install command, and re-run with "
                "--cloudflare-tunnel-token <token>."
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

    # Preflight: lan_direct + any public exposure is not a supported
    # combination. lan_direct sends the participant's browser straight to
    # a client's LAN IP (ws://<client-ip>:6080 — see
    # LANDirectClientConnectivity), bypassing the allocator entirely —
    # unreachable off-LAN and blocked as mixed content once the allocator
    # itself is publicly exposed. mesh_overlay proxies sessions through the
    # allocator's own nginx instead, which any exposure mode publishes.
    # get_config_errors() also rejects this (catches it in the wizard/
    # `show-config`/`doctor`), but `lablink deploy` never calls that
    # validator for the manual provider — this is the actual enforcement
    # point for a hand-edited config.yaml deployed directly.
    if (
        cfg.manual.participant_exposure != "none"
        and cfg.manual.connectivity == "lan_direct"
    ):
        console.print(
            f"[red]manual.participant_exposure is "
            f"'{cfg.manual.participant_exposure}' but manual.connectivity is "
            f"'lan_direct'.[/red]\n"
            "Participant sessions would connect directly to a client's LAN "
            "IP, which is unreachable off-LAN and blocked as mixed content "
            "from the HTTPS page. Use manual.connectivity: mesh_overlay "
            "instead, which proxies sessions through the allocator."
        )
        raise SystemExit(1)

    # Preflight: docker on PATH.
    try:
        docker.require()
    except DockerUnavailable:
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

    # Preflight: a publicly exposed allocator is scanned by bots within
    # minutes of publication (empirically confirmed 2026-07-22) — refuse
    # to ship a weak/example admin password once that's the case. Placed
    # after resolve_admin_credentials so a value resolved interactively
    # is what actually gets checked, not whatever (possibly empty) value
    # cfg.app.admin_password held before resolution.
    if cfg.manual.participant_exposure != "none":
        from lablink_allocator_service.validate_config import is_weak_admin_password

        if is_weak_admin_password(admin_pw):
            console.print(
                f"[red]manual.participant_exposure is "
                f"'{cfg.manual.participant_exposure}' but the resolved admin "
                "password is empty, a known example value, or shorter than "
                "12 characters.[/red]\n"
                "A publicly exposed allocator is reachable from the internet "
                "and gets scanned within minutes — set a strong "
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

    # Initialize deployment metrics — written incrementally so a failed
    # deploy still leaves a record on disk, same as the AWS path. Started
    # here, after the confirmation gate, so an aborted "Proceed?" leaves no
    # in_progress file behind at all. region/template_version stay None:
    # there is no region and no OpenTofu template in a compose deploy.
    deploy_start_dt = datetime.now(timezone.utc)
    metrics = DeploymentMetrics(
        deployment_name=cfg.deployment_name,
        provider="manual",
        ssl_enabled=cfg.ssl.provider != "none",
        allocator_deploy_start_time=deploy_start_dt.isoformat(),
    )
    metrics_path = cache_path_for(cfg.deployment_name, deploy_start_dt)
    write_metrics(metrics_path, metrics)

    # Everything from here to the success write is inside the try: the record
    # already exists on disk, so any escape that skips the write below strands
    # it at in_progress — indistinguishable from a Ctrl-C, and with null
    # timings. render_compose_dir writes files and calls save_config, and
    # _write_canonical_url writes one too, so OSError is live in both stretches
    # either side of the timed phases, not just in the phases themselves.
    try:
        render_compose_dir(
            cfg,
            target,
            tailscale_authkey=tailscale_authkey,
            cloudflare_tunnel_token=cloudflare_tunnel_token,
        )
        console.print(f"[green]Rendered {target}[/green]")

        # Explicitly disable Funnel *before* _compose_up, whenever the new
        # config no longer wants it — this must run before --remove-orphans
        # potentially deletes the sidecar (a removed container can't be
        # `docker exec`'d into), and it's needed even when the sidecar
        # sticks around unchanged (e.g. connectivity=mesh_overlay alone),
        # since Funnel persists in the sidecar's own state regardless of
        # whether _enable_funnel keeps getting called. See _disable_funnel.
        if cfg.manual.participant_exposure != "tailscale_funnel":
            _disable_funnel(docker=docker)

        with phase_timer(
            metrics, "allocator_compose_up_duration_seconds", metrics_path
        ):
            _compose_up(target, docker=docker)
        with phase_timer(
            metrics, "allocator_health_check_duration_seconds", metrics_path
        ):
            _health_poll(docker=docker)

        # Disable again, now that the sidecar (if the compose file still
        # declares one) is guaranteed running. The call above can silently
        # no-op if the sidecar was stopped-but-not-removed at that point —
        # `docker exec` fails on a stopped container the same way it does on
        # a missing one, and _disable_funnel() can't tell those apart. If
        # connectivity stays mesh_overlay, _compose_up just restarted that
        # same stopped sidecar, reattached to tailscale_state with Funnel's
        # last-known "on" config still intact — this second call is what
        # actually clears it. Harmless no-op if the sidecar was removed as
        # an orphan instead (nothing to disable).
        if cfg.manual.participant_exposure != "tailscale_funnel":
            _disable_funnel(docker=docker)

        funnel_ok = True
        funnel_url = None
        if cfg.manual.participant_exposure == "tailscale_funnel":
            funnel_ok, funnel_url = _enable_funnel(docker=docker)
            if funnel_url:
                _write_canonical_url(target, funnel_url)

        if cfg.manual.participant_exposure == "cloudflare_tunnel":
            if not _verify_public_hostname(cfg.manual.public_hostname):
                console.print(
                    f"[yellow]https://{cfg.manual.public_hostname} did not "
                    "answer.[/yellow]\n"
                    "The stack is up locally. Common causes: the DNS record is "
                    "still propagating (retry in a few minutes), or the "
                    "tunnel's public hostname in Cloudflare does not point at "
                    "http://localhost:5000."
                )
                _print_last_log_lines(docker=docker)
    except (Exception, SystemExit) as e:
        # SystemExit IS caught here, unlike the AWS path where it means "user
        # cancelled" and in_progress is the honest state. Nothing in this
        # stretch is a cancellation — _compose_up and _health_poll both raise
        # SystemExit for a genuine failure (non-zero compose exit, health
        # timeout), so leaving those as in_progress would under-report real
        # failures. KeyboardInterrupt is a BaseException and still escapes.
        metrics.status = "failed"
        metrics.error = str(e)
        write_metrics(metrics_path, metrics)
        raise

    funnel_active = cfg.manual.participant_exposure == "tailscale_funnel" and funnel_ok

    # Total = sum of the timed phases, matching the AWS path's definition
    # (machine work only, excluding prompt time). Exposure setup — Funnel
    # enable, public-hostname verification — is deliberately untimed, so a
    # slow DNS propagation doesn't masquerade as slow deploy machinery.
    metrics.allocator_deploy_end_time = datetime.now(timezone.utc).isoformat()
    metrics.allocator_total_deployment_duration_seconds = round(
        sum(
            v
            for v in (
                metrics.allocator_compose_up_duration_seconds,
                metrics.allocator_health_check_duration_seconds,
            )
            if v is not None
        ),
        3,
    )
    metrics.status = "success" if funnel_ok else "failed"
    if not funnel_ok:
        metrics.error = "tailscale funnel could not be enabled"
    write_metrics(metrics_path, metrics)

    _print_summary(
        cfg, funnel_active=funnel_active, funnel_url=funnel_url, docker=docker
    )

    if not funnel_ok:
        raise SystemExit(1)


def _verify_public_hostname(hostname: str) -> bool:
    """True if the allocator answers on its public hostname.

    One request over the real public URL proves DNS resolution, the
    Cloudflare edge, the tunnel, nginx and Flask together — checking that
    cloudflared is alive says nothing about whether the edge found it.

    Polled, because the local `_health_poll` above clears as soon as Flask
    answers — which is *before* the public path exists. cloudflared is still
    registering its edge connections at that point and nginx is still binding
    :5000, so a single attempt fails on a perfectly good deploy (observed
    live 2026-08-05: warned at 20:25:30, the same container served the public
    hostname seconds later and stayed up).

    Still advisory, and bounded short: the remaining failure modes — a
    still-propagating DNS record, or a public hostname in the Cloudflare
    dashboard pointing somewhere other than the origin — are not things
    waiting fixes, and the caller only warns.
    """
    url = f"https://{hostname}"
    console.print(
        f"[bold]Verifying public hostname {url}/api/health "
        f"(up to {PUBLIC_HOSTNAME_MAX_ATTEMPTS} tries) …[/bold]"
    )
    for attempt in range(1, PUBLIC_HOSTNAME_MAX_ATTEMPTS + 1):
        try:
            healthy = bool(check_health_endpoint(url).get("healthy"))
        except OSError:
            # Unresolvable name / refused connection while the record
            # propagates, or while the tunnel route is still coming up.
            healthy = False
        if healthy:
            console.print(f"[green]Public hostname is live: {url}[/green]")
            return True
        if attempt < PUBLIC_HOSTNAME_MAX_ATTEMPTS:
            time.sleep(PUBLIC_HOSTNAME_RETRY_DELAY_SECONDS)
    return False


def _compose_up(target: Path, *, docker: Docker) -> None:
    console.print("[bold]docker compose up -d …[/bold]")
    # --remove-orphans: if needs_sidecar just became False (connectivity
    # switched off mesh_overlay AND participant_exposure switched off
    # tailscale_funnel), the freshly-rendered compose file no longer
    # declares the tailscale service — without this flag, `docker
    # compose up` leaves that now-undeclared container running
    # untouched, forever. _disable_funnel() (called before this, in
    # run_deploy_compose) already clears its Funnel state first, so
    # this just ensures the container itself doesn't linger too.
    result = docker.compose(target, "up", "-d", "--remove-orphans", capture=False)
    if not result.ok:
        console.print("[red]docker compose up failed.[/red]")
        raise SystemExit(result.returncode or 1)


def _write_canonical_url(target: Path, url: str) -> None:
    """Publish the allocator's real public URL to the bind-mounted file the
    allocator reads (see config_helpers.canonical_base_url).

    Behind Funnel the allocator cannot work its own public URL out from the
    request: Funnel injects no X-Forwarded-Proto, and manual deployments run
    ssl.provider=none so the header-trust gate is shut anyway. It therefore
    reports http://, which clients can only follow via a 302 that downgrades
    their POSTs to GET. This file is the out-of-band channel that fixes that,
    carrying the address `tailscale funnel status` actually reported — which
    also picks up the numeric hostname suffixes (-2, -3, ...) that a name
    collision with an offline node from a prior deploy produces.

    Written IN PLACE, never via a temp file + rename: docker bind-mounts a
    single file by inode, so a rename would leave the running container
    reading the old file forever.
    """
    path = target / CANONICAL_URL_FILENAME
    with path.open("w") as f:
        f.write(f"{url.rstrip('/')}\n")


FUNNEL_STATUS_URL_RE = re.compile(r"(https://\S+)\s*\(Funnel on\)")


def _funnel_status_url(*, docker: Docker) -> str | None:
    """Query the sidecar for the public URL Tailscale Funnel is actually
    serving right now, via `tailscale funnel status`.

    This is the authoritative source for the URL — Tailscale assigns the
    node's hostname, and it does not necessarily match
    `lablink-allocator-<deployment_name>`: a name collision with an
    existing (possibly offline) tailnet node from a prior deploy gets a
    numeric suffix appended instead (verified live: `-2`, `-3`, ... after
    repeated deploy/destroy cycles). Returns None if Funnel isn't active
    or the output didn't match the expected format.
    """
    result = docker.exec_in(
        TAILSCALE_SIDECAR_CONTAINER_NAME,
        ["tailscale", "funnel", "status"],
    )
    match = FUNNEL_STATUS_URL_RE.search(result.stdout)
    return match.group(1) if match else None


def _enable_funnel(*, docker: Docker) -> tuple[bool, str | None]:
    """Idempotently enable Tailscale Funnel on the allocator's own nginx
    port, via the sidecar container.

    `tailscale funnel`'s config lives in tailscaled's own local state
    (already persisted by the compose file's `tailscale_state` named
    volume), so this is safe to re-run on every deploy — a no-op if
    already enabled. If the tailnet hasn't granted the Funnel ACL yet,
    the command's own output names the exact grant URL; this surfaces
    that URL and returns (False, None) rather than silently leaving the
    allocator unreachable to participants.

    Retries a few times with a short delay: the sidecar may still be
    completing its own `tailscale up` join when this runs (right after
    `_compose_up`/`_health_poll`, which only confirm the *allocator*
    container is healthy, not the sidecar's tailnet membership) — the
    same class of startup race already fixed on the client side (commit
    7a8ab9f6). Only retried for transient not-ready-yet failures; an
    ACL-not-granted response is unambiguous and returned immediately
    without retrying, since retrying can't fix a missing grant.

    Returns (True, url) if Funnel is enabled (or already was) — url is
    the real address from `_funnel_status_url()`, or None if that lookup
    didn't find one despite the enable itself succeeding. Returns
    (False, None) otherwise (ACL not granted, or failure persisting
    across all retries) — callers should still let the rest of the
    deploy complete either way (the stack is functional for LAN/
    mesh-overlay access regardless), but should ultimately exit non-zero
    when this returns False.
    """
    for attempt in range(1, FUNNEL_ENABLE_MAX_ATTEMPTS + 1):
        result = docker.exec_in(
            TAILSCALE_SIDECAR_CONTAINER_NAME,
            ["tailscale", "funnel", "--bg", str(ALLOCATOR_INTERNAL_PORT)],
        )
        output = result.stdout + result.stderr
        if FUNNEL_ACL_NOT_GRANTED_MARKER in output:
            console.print(
                "[yellow]Tailscale Funnel isn't authorized on this tailnet "
                "yet.[/yellow] The compose stack is up and reachable on your "
                "LAN, but participant exposure needs a one-time grant:\n"
            )
            console.print(output.strip())
            return False, None
        if result.returncode == 0:
            console.print(
                "[green]Tailscale Funnel enabled for participant access.[/green]"
            )
            console.print(output.strip())
            return True, _funnel_status_url(docker=docker)
        if attempt < FUNNEL_ENABLE_MAX_ATTEMPTS:
            time.sleep(FUNNEL_ENABLE_RETRY_DELAY_SECONDS)
            continue
        console.print(
            f"[red]Failed to enable Tailscale Funnel after "
            f"{FUNNEL_ENABLE_MAX_ATTEMPTS} attempts (exit "
            f"{result.returncode}):[/red]\n{output.strip()}"
        )
        return False, None


def _disable_funnel(*, docker: Docker) -> None:
    """Explicitly clear Tailscale Funnel's serve config on the sidecar,
    best-effort.

    `tailscale funnel --bg` persists in tailscaled's own local state (the
    `tailscale_state` named volume) across container restarts — and even
    across container *recreation*, since a freshly-created sidecar
    reattaches to that same volume and the same node identity resumes
    serving from its last-known config. Simply no longer calling
    `_enable_funnel()` is NOT enough to actually turn Funnel off; it has
    to be explicitly disabled, or a previously-Funnel-exposed allocator
    stays publicly reachable even after an operator sets
    participant_exposure back to "none".

    Called whenever the new config's participant_exposure is no longer
    "tailscale_funnel", *before* `_compose_up` — including the case
    where the sidecar is about to be removed entirely as a compose
    orphan (needs_sidecar became False), since a removed container can
    no longer be `docker exec`'d into and its persisted volume would
    otherwise carry the stale "enabled" state forward to any future
    sidecar that reattaches to it.

    Best-effort and silent on failure: if the sidecar container doesn't
    exist at all (e.g. a fresh deployment that never enabled Funnel),
    there is nothing to disable and no error is surfaced.
    """
    result = docker.exec_in(
        TAILSCALE_SIDECAR_CONTAINER_NAME,
        ["tailscale", "funnel", "--https=443", "off"],
    )
    if result.ok:
        console.print("[dim]Tailscale Funnel disabled.[/dim]")


def _health_poll(*, docker: Docker) -> None:
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
            console.print(f"[green]Allocator healthy after {elapsed:.0f}s[/green]")
            return
        time.sleep(3)

    console.print(
        "[yellow]Allocator did not become healthy within "
        f"{HEALTH_POLL_TIMEOUT_SECONDS}s.[/yellow]"
    )
    _print_last_log_lines(docker=docker)
    raise SystemExit(1)


def _redact_secrets(text: str) -> str:
    """Blank out credential values in container output before printing it.

    Keyed on the variable *name*, not the value's shape: a Cloudflare token
    is base64-ish and a tailnet auth key is `tskey-`-prefixed, but both are
    the vendor's to change, whereas the names are ours.

    Needed because `cloudflared` logs its whole environment at INFO on
    startup. `start.sh` unsets the token before launching it, so a current
    image never logs it — this is the second layer, covering images built
    before that change and any other path that echoes a secret.
    """
    return re.sub(
        r"((?:CLOUDFLARE_TUNNEL_TOKEN|TS_AUTHKEY)[=:]|--token[= ])\S+",
        r"\1<redacted>",
        text,
    )


def _print_last_log_lines(lines: int = 30, *, docker: Docker) -> None:
    # Merge stderr: the allocator's Python logging goes there (see
    # _extract_register_token), so capturing the streams separately and
    # printing only stdout hid the very tracebacks this dump exists to
    # surface. Merging is also why the redaction above is load-bearing.
    result = docker.logs(ALLOCATOR_CONTAINER_NAME, tail=lines, merge_stderr=True)
    if result.stdout:
        console.print("[dim]Last allocator log lines:[/dim]")
        console.print(_redact_secrets(result.stdout))


def _print_summary(
    cfg: Config,
    *,
    funnel_active: bool = False,
    funnel_url: str | None = None,
    docker: Docker,
) -> None:
    register_token = _extract_register_token(docker=docker)
    # Manual provider is HTTP-only; preflight rejects anything else.
    local_url = "http://localhost"
    lan_ip = _detect_lan_ip()
    lan_url = f"http://{lan_ip}" if lan_ip else None
    # BYO clients run on different boxes, so the register command needs
    # an address those boxes can route to — localhost is only useful for
    # self-registration on the operator's host. Prefer the LAN URL when
    # we could detect one.
    register_url = lan_url or local_url

    # The deployment's one internet-reachable URL, or None. Funnel's has to
    # be read back out of the sidecar and can be missing even when enabled;
    # Cloudflare's is just config the admin typed. Everything downstream only
    # cares whether such a URL exists, so both collapse into one value here
    # rather than each exposure mode growing its own branch.
    if funnel_active and funnel_url:
        public_url = funnel_url
    elif cfg.manual.participant_exposure == "cloudflare_tunnel":
        public_url = f"https://{cfg.manual.public_hostname}"
    else:
        public_url = None

    console.print("\n[bold green]Deployment complete.[/bold green]")
    if funnel_active and not funnel_url:
        console.print(
            "  Allocator URL (public): (enabled, but the URL could not be "
            f"determined — run `docker exec {TAILSCALE_SIDECAR_CONTAINER_NAME} "
            "tailscale funnel status` to see it)",
            soft_wrap=True,
            highlight=False,
        )
    elif public_url:
        console.print(
            f"  Allocator URL (public): {public_url}",
            soft_wrap=True,
            highlight=False,
        )
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
    # public_url and lan_direct are mutually exclusive (preflight above), so
    # this chain encodes the connectivity rule without re-reading it.
    admin_url = public_url or lan_url or local_url
    # soft_wrap: a real Funnel URL plus the column prefix overruns 80 cols.
    console.print(
        f"  Admin URL:             {admin_url}/admin",
        soft_wrap=True,
        highlight=False,
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
    reverse_tunnel = cfg.manual.connectivity == "reverse_tunnel"
    # Both connectivity modes below mean the client isn't reachable on the
    # allocator's own LAN — mesh_overlay via a Tailscale tailnet,
    # reverse_tunnel by dialing out instead of accepting inbound at all.
    off_lan = mesh_overlay or reverse_tunnel
    # Substitute only when a real public URL exists — funnel_active can be
    # True while funnel_url is None (enable succeeded but the status lookup
    # didn't match), and a guessed fallback here would be exactly the wrong
    # URL this function used to print. Gated on off_lan, not just
    # mesh_overlay: a reverse_tunnel client behind a NAT'd/firewalled box is
    # just as unreachable at the LAN address. Gated on public_url rather
    # than on Funnel specifically, because an off-LAN client cannot reach
    # the LAN address no matter which exposure mode publishes the
    # allocator — printing one is how this hint was wrong before.
    public_url_used = off_lan and bool(public_url)
    # Hoisted above the mesh_overlay/reverse_tunnel branch so both off-LAN
    # modes get the substitution — lan_direct clients genuinely are on the
    # LAN, so their own hint below keeps using register_url as-is.
    if public_url_used:
        register_url = public_url
    if mesh_overlay:
        # A mesh-overlay client (e.g. a Run:AI-hosted workload) isn't on
        # the allocator's LAN at all — the LAN URL above is unreachable
        # from it regardless of whether we detected one. Whichever exposure
        # mode is live, its public URL IS reachable from anywhere with
        # internet access, so prefer that here.
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
    elif reverse_tunnel:
        console.print(
            "\n[bold]Next step:[/bold] for each tunnel client (a box or "
            "workload that can't accept inbound connections), open a "
            "terminal inside it and run (hostname/machine-identity/GPU are "
            "auto-detected; the tunnel's values are minted by the "
            "allocator, so --tunnel takes no arguments):"
        )
        register_cmd = (
            f"  lablink client register --allocator-url {register_url} "
            f"--register-token {register_token or '<token>'} --tunnel"
        )
    else:
        console.print("\n[bold]Next step:[/bold] on each BYO box on the same LAN, run")
        register_cmd = (
            f"  lablink client register --allocator-url {register_url} "
            f"--register-token {register_token or '<token>'}"
        )
    console.print(register_cmd, soft_wrap=True, highlight=False)
    if off_lan:
        console.print(
            "  [dim]Registering ahead of time from elsewhere instead? "
            "Add --no-run-locally to print secrets for your own "
            "workload submission instead of running here, along with "
            "--hostname/--machine-identity.[/dim]"
        )
    if not lan_url and not public_url_used:
        # If we fell back to localhost, the printed command only works
        # for a BYO client *on the operator host*. Call that out so the
        # operator doesn't blindly hand it to a remote teammate. Doesn't
        # apply when the off-LAN hint above already substituted a public
        # URL instead of falling back to localhost.
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


def _extract_register_token(*, docker: Docker) -> str | None:
    """Parse the register_token from the allocator's startup logs.

    The allocator logs `REGISTER_TOKEN=<token>` at startup (grep for
    `REGISTER_TOKEN=%s` in `lablink_allocator_service/main.py`).
    Also tolerate the `register_token = "..."` form just in case.

    Python's `logging.basicConfig` writes to stderr, so `merge_stderr=True`
    is required here too — see `Docker.logs`.
    """
    result = docker.logs(ALLOCATOR_CONTAINER_NAME, merge_stderr=True)
    if not result.ok:
        return None
    for pattern in (
        r'REGISTER_TOKEN\s*=\s*"?([A-Za-z0-9_\-]{20,})"?',
        r'register_token\s*=\s*"?([A-Za-z0-9_\-]{20,})"?',
    ):
        m = re.search(pattern, result.stdout)
        if m:
            return m.group(1)
    return None


def _pgdata_volume_name(target: Path, *, docker: Docker) -> str | None:
    """Resolve the Docker volume currently backing the allocator's Postgres data.

    Tries the running container's actual mount first (exact, no guessing).
    Falls back to Compose's own directory-basename project-naming
    convention when the container's already gone — e.g. an operator ran a
    manual `docker compose down` (removing containers, leaving volumes)
    before `lablink destroy` — verified via `docker volume inspect` before
    trusting it, so a wrong guess can't be silently mistaken for "nothing
    to remove". Guessing is safe here specifically because deployment_name
    (and therefore target.name) is already regex-constrained to Compose's
    own project-name character set (`^[a-z][a-z0-9-]*[a-z0-9]$` — see
    config/schema.py's DEPLOYMENT_NAME_RE), so there's no normalization
    mismatch to worry about.

    Returns None only if no volume can be found by either method — i.e.
    this deployment never actually created one.
    """
    name = docker.inspect_format(
        ALLOCATOR_CONTAINER_NAME,
        '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql"}}'
        "{{.Name}}{{end}}{{end}}",
    )
    if name:
        return name

    candidate = f"{target.name}_allocator_pgdata"
    return candidate if docker.volume_exists(candidate) else None


def run_destroy_compose(
    cfg: Config,
    *,
    yes: bool = False,
    keep_data: bool = False,
    workdir_root: Path | None = None,
    docker: Docker | None = None,
) -> None:
    """Tear down a manual-provider compose stack.

    Default behavior: wipes the Postgres data volume (all registration
    history, sessions, etc.) plus the working directory. A subsequent
    `lablink deploy` with the same deployment_name then starts from a
    genuinely empty database, matching what "destroy" means for every
    other provider — previously the default silently preserved the old
    volume, so a "fresh" redeploy kept showing every client registered
    under a prior deployment.

    The Postgres volume is removed by name (resolved via `_pgdata_volume_name`)
    rather than via `docker compose down --volumes`, which would also delete
    the mesh-overlay `tailscale_state` volume — that volume carries the
    Tailscale node's identity, not "data": wiping it forces a brand-new
    tailnet registration on the next deploy, which changes the node's
    hostname (and any Funnel URL already handed to participants) for no
    reason. `tailscale_state` is always preserved, independent of `keep_data`.

    With `keep_data=True`: no volumes are touched at all, and the working
    directory is left in place — re-deploying with the same deployment_name
    restores the previous DB state instead of starting fresh. Opt into this
    only if that's specifically what you want (e.g. a deliberate maintenance
    restart, not a real teardown).

    `yes=True` skips the interactive confirmation prompt.
    `workdir_root` overrides `DEFAULT_COMPOSE_DIR` (used by tests).
    """
    docker = docker or default_docker()
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

    pgdata_volume = None if keep_data else _pgdata_volume_name(target, docker=docker)

    result = docker.compose(target, "down", capture=False)
    if not result.ok:
        console.print("[red]docker compose down failed.[/red]")
        raise SystemExit(result.returncode or 1)

    if not keep_data:
        if pgdata_volume:
            rm_result = docker.remove_volume(pgdata_volume)
            if not rm_result.ok:
                console.print(
                    f"[red]Failed to remove Postgres volume "
                    f"{pgdata_volume}:[/red] {rm_result.stderr.strip()}\n"
                    "The working directory was NOT removed — a later "
                    "deploy could otherwise silently reattach to this "
                    "volume's old data. Resolve the error above and "
                    "re-run `lablink destroy`."
                )
                raise SystemExit(1)
        shutil.rmtree(target)
        console.print(f"[green]Removed {target}.[/green]")
    else:
        console.print(f"[green]Stack torn down (data preserved in {target}).[/green]")

    console.print(
        "\n[bold]Reminder:[/bold] each BYO client box still has "
        "`lablink-client` running.\n"
        "Run [bold]lablink client unregister[/bold] on each box to clean up."
    )
