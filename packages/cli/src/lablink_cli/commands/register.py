"""`lablink client register` — register a BYO box as a manual client."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import psutil

from rich.console import Console

from lablink_cli import byo_detect
from lablink_cli.log_shipper import inspect_container as inspect_container_for_register
from lablink_cli.api import (
    AllocatorAuthError,
    AllocatorConflictError,
    AllocatorError,
    AllocatorUnavailableError,
    RegistrationClient,
)

DEFAULT_ENV_FILE = Path.home() / ".lablink" / "client.env"
# Distinct from the operator-side override at ~/.lablink/custom-startup.sh
# (read by deploy.py:101-103) so that running operator + BYO client on the
# same box doesn't have the client-received copy clobber the operator's
# local override.
DEFAULT_STARTUP_SCRIPT = Path.home() / ".lablink" / "client-custom-startup.sh"
PID_FILE = Path.home() / ".lablink" / "log_shipper.pid"


def _detect_hostname(hostname: str | None, console: Console) -> str:
    resolved = hostname or byo_detect.detect_hostname()
    if not resolved:
        console.print(
            "[red]Could not detect hostname.[/red] "
            "Pass --hostname explicitly."
        )
        raise SystemExit(1)
    console.print(f"Detected hostname: {resolved}")
    return resolved


def _detect_machine_identity(machine_identity: str | None, console: Console) -> str:
    resolved = machine_identity or byo_detect.resolve_machine_identity()
    console.print(f"Detected machine identity: {resolved}")
    return resolved


def _detect_gpu(
    gpu_present: bool | None, gpu_model: str | None, console: Console
) -> tuple[bool, str | None]:
    detected_present, detected_model = byo_detect.detect_gpu()
    resolved_present = gpu_present if gpu_present is not None else detected_present
    resolved_model = gpu_model or detected_model
    console.print(
        f"Detected GPU: {resolved_model}"
        if resolved_present
        else "Detected GPU: none"
    )
    return resolved_present, resolved_model


def run_register(
    *,
    allocator_url: str,
    register_token: str,
    hostname: str | None,
    lan_ip: str | None,
    machine_identity: str | None,
    gpu_present: bool | None,
    gpu_model: str | None,
    force: bool,
    env_file: Path | None,
    insecure: bool,
    overlay_hostname: str | None = None,
    tailscale_authkey: str | None = None,
    run_locally: bool = True,
) -> None:
    """Orchestrate registration. Exits non-zero on any user-facing error.

    Three shapes:
    - Real BYO box (default): auto-detects hostname/LAN IP/machine
      identity/GPU, then docker-runs the client container after
      persisting secrets.
    - Mesh-overlay, run locally (``overlay_hostname`` set, ``run_locally``
      true — the default): the box registering *is* the target client
      right now (e.g. a terminal inside an already-running Run:AI
      workload with docker-in-docker), so hostname/machine-identity/GPU
      are auto-detected the same as real BYO, and the client container
      is docker-run immediately, joining the Tailscale tailnet on start.
    - Mesh-overlay, hand-off (``overlay_hostname`` set, ``run_locally``
      false via ``--no-run-locally``): the box doesn't exist yet, so
      auto-detection is skipped entirely (it would report *this*
      machine's own facts); ``--hostname``/``--machine-identity`` are
      required. No docker run — instead prints the secrets for the
      admin to paste into their own workload submission.
    """
    console = Console()
    env_file = env_file or DEFAULT_ENV_FILE

    if overlay_hostname is None:
        if not run_locally:
            console.print(
                "[red]--no-run-locally only applies with "
                "--overlay-hostname.[/red]"
            )
            raise SystemExit(1)
    else:
        if not tailscale_authkey:
            console.print(
                "[red]--tailscale-authkey is required with "
                "--overlay-hostname.[/red]"
            )
            raise SystemExit(1)
        if not run_locally:
            if not hostname:
                console.print(
                    "[red]--hostname is required with --overlay-hostname "
                    "--no-run-locally.[/red] Auto-detection would report "
                    "this machine's own hostname, not the future "
                    "client's — the client doesn't exist yet."
                )
                raise SystemExit(1)
            if not machine_identity:
                console.print(
                    "[red]--machine-identity is required with "
                    "--overlay-hostname --no-run-locally.[/red] "
                    "Auto-detection would report this machine's own "
                    "identity, not the future client's."
                )
                raise SystemExit(1)

    # Step 1: idempotency / resume. Skipped only for the mesh-overlay
    # hand-off case (overlay_hostname set, run_locally false) — that
    # case has no local container/env-file lifecycle to resume.
    if (
        (overlay_hostname is None or run_locally)
        and env_file.exists()
        and not force
    ):
        _resume(env_file, console)
        return

    if overlay_hostname is not None:
        console.print(f"Registering overlay hostname: {overlay_hostname}")
        if run_locally:
            resolved_hostname = _detect_hostname(hostname, console)
            resolved_machine_identity = _detect_machine_identity(
                machine_identity, console
            )
            resolved_gpu_present, resolved_gpu_model = _detect_gpu(
                gpu_present, gpu_model, console
            )
        else:
            resolved_hostname = hostname
            resolved_machine_identity = machine_identity
            resolved_gpu_present = bool(gpu_present)
            resolved_gpu_model = gpu_model
    else:
        # Step 2: auto-detect (user overrides win)
        resolved_hostname = _detect_hostname(hostname, console)

        resolved_lan_ip = lan_ip or byo_detect.detect_lan_ip()
        if not resolved_lan_ip:
            console.print(
                "[red]Could not detect LAN IP.[/red] "
                "Pass --lan-ip explicitly."
            )
            raise SystemExit(1)
        console.print(f"Detected LAN IP: {resolved_lan_ip}")

        resolved_machine_identity = _detect_machine_identity(
            machine_identity, console
        )
        resolved_gpu_present, resolved_gpu_model = _detect_gpu(
            gpu_present, gpu_model, console
        )

    # Step 3 + 4: build + POST
    ssl_provider = "self_signed" if insecure else "none"
    client = RegistrationClient(
        allocator_url, register_token, ssl_provider=ssl_provider
    )
    console.print(f"Registering with {allocator_url} …")
    try:
        if overlay_hostname is not None:
            response = client.register(
                hostname=resolved_hostname,
                machine_identity=resolved_machine_identity,
                overlay_hostname=overlay_hostname,
                gpu_present=resolved_gpu_present,
                gpu_model=resolved_gpu_model,
            )
        else:
            response = client.register(
                hostname=resolved_hostname,
                machine_identity=resolved_machine_identity,
                lan_ip=resolved_lan_ip,
                gpu_present=resolved_gpu_present,
                gpu_model=resolved_gpu_model,
            )
    except AllocatorAuthError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1) from e
    except AllocatorConflictError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1) from e
    except AllocatorUnavailableError as e:
        console.print(f"[red]Allocator unreachable: {e}[/red]")
        raise SystemExit(1) from e
    except AllocatorError as e:
        console.print(f"[red]{e}[/red]")
        raise SystemExit(1) from e

    # Step 5: persist env file (0600)
    _write_env_file(
        env_file,
        allocator_url,
        response,
        overlay_hostname=overlay_hostname,
        tailscale_authkey=tailscale_authkey,
    )
    console.print(
        f"[green]Secrets saved to {env_file} (mode 0600)[/green]"
    )

    if overlay_hostname is not None and not run_locally:
        # No host for the CLI to act on — the Run:AI workload doesn't
        # exist yet. Print everything the admin needs to paste into
        # their own workload submission instead of docker-running
        # anything. The loop below already emits OVERLAY_HOSTNAME/
        # TAILSCALE_AUTHKEY since _write_env_file now includes them.
        console.print(
            "\n[bold]No local container will be started[/bold] — this "
            "box doesn't exist yet. Paste the following into your "
            "Run:AI workload's environment variables:\n"
        )
        for line in env_file.read_text().splitlines():
            if line.startswith("#"):
                continue
            print(line)
        return

    # Step 6: GPU runtime pre-flight (only when --gpus all will be added)
    if resolved_gpu_present:
        _verify_gpu_runtime(console)

    # Step 7 + 8: docker run (always)
    startup_script_path = _write_startup_script(response)
    cmd = _build_docker_run(
        env_file, response, resolved_gpu_present, startup_script_path,
        overlay_hostname,
    )
    console.print(
        f"[green]Registered as client #{response['client_id']}[/green]"
    )
    _exec_docker(cmd, console)
    if overlay_hostname is not None:
        console.print(
            "[dim]This container joins Tailscale as "
            f"{overlay_hostname} on start — confirm with "
            "`docker logs lablink-client`.[/dim]"
        )
    _start_log_shipper(env_file, console)


def _resume(env_file: Path, console: Console) -> None:
    """Re-run mode for an already-registered host.

    Does NOT mint a new client_secret. Restarts the container if stopped,
    revives the shipper if dead, otherwise prints a no-op message.

    Note: container image is NOT re-pulled — that's `--force` territory.
    """
    status = inspect_container_for_register("lablink-client")
    container_action: str | None = None

    if status == "missing":
        console.print(
            "[yellow]Already registered, but lablink-client container is "
            "missing.[/yellow] Re-run with [bold]--force[/bold] to recreate "
            "it (this mints a new client_secret)."
        )
        raise SystemExit(1)
    if status == "daemon_error":
        console.print(
            "[red]Docker daemon is unreachable.[/red] Start Docker and re-run."
        )
        raise SystemExit(1)
    if status in ("exited", "restarting"):
        try:
            subprocess.run(
                ["docker", "start", "lablink-client"],
                check=True,
                capture_output=True,
            )
            container_action = "restarted"
        except subprocess.CalledProcessError as e:
            console.print(
                f"[red]docker start lablink-client failed:[/red] "
                f"{e.stderr.decode().strip() if e.stderr else e}"
            )
            raise SystemExit(1) from e

    shipper_action: str | None = None
    if _shipper_alive():
        if container_action is None:
            console.print(
                "[green]Already registered. Container and log shipper "
                "are running.[/green]"
            )
            return
    else:
        _start_log_shipper(env_file, console)
        shipper_action = "restarted"

    if container_action and shipper_action:
        console.print(
            "[green]Restarted container and log shipper.[/green] "
            "To pull a newer client image, re-run with --force."
        )
    elif container_action:
        console.print(
            "[green]Restarted container.[/green] "
            "To pull a newer client image, re-run with --force."
        )
    elif shipper_action:
        console.print("[green]Restarted log shipper.[/green]")


def _write_env_file(
    env_file: Path,
    allocator_url: str,
    resp: dict,
    *,
    overlay_hostname: str | None = None,
    tailscale_authkey: str | None = None,
) -> None:
    env_file.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    resolved_url = resp.get("allocator_url") or allocator_url
    allocator_host = urlparse(resolved_url).hostname or ""
    # REGISTER_RESPONSE is the full server response, re-serialized as
    # single-line JSON. The client's start.sh parses it to materialize
    # /tmp/lablink-monitoring.json (and any future server-shipped settings).
    # docker --env-file reads each line verbatim up to newline; json.dumps()
    # without indent=... never emits a literal newline, so this is safe.
    register_response_json = json.dumps(resp, separators=(",", ":"))
    lines = [
        f"# Generated by `lablink client register` on {timestamp}",
        f"CLIENT_ID={resp['client_id']}",
        f"VM_NAME={resp['client_id']}",
        f"CLIENT_SECRET={resp['client_secret']}",
        f"AGENT_TOKEN={resp['agent_token']}",
        f"REGISTER_TOKEN={resp['register_token']}",
        f"ALLOCATOR_URL={resolved_url}",
        f"ALLOCATOR_HOST={allocator_host}",
        f"CONNECTIVITY={resp['connectivity']}",
        f"CLIENT_IMAGE={resp['client_image']}",
        f"REGISTER_RESPONSE={register_response_json}",
    ]
    if overlay_hostname is not None:
        # Written so a nested `docker run --env-file` (the run_locally
        # path) carries these into the container automatically —
        # start.sh's existing `if [ -n "$TAILSCALE_AUTHKEY" ]` gate then
        # joins the tailnet with no client-image changes needed.
        lines.append(f"OVERLAY_HOSTNAME={overlay_hostname}")
        lines.append(f"TAILSCALE_AUTHKEY={tailscale_authkey}")
    env_file.write_text("\n".join(lines) + "\n")
    env_file.chmod(0o600)


def _write_startup_script(resp: dict) -> Path | None:
    """Materialize the allocator-provided startup script to disk.

    Returns the host path to bind-mount into the client container, or
    None when the allocator returned no script (disabled, file missing,
    or empty). Mode 0755 so root-in-container can exec it via ``bash``.
    Stale files from prior registrations are removed when the current
    response carries no payload, so a script disabled on the allocator
    side is not silently kept alive locally.
    """
    b64 = resp.get("startup_script_b64") or ""
    if not b64:
        DEFAULT_STARTUP_SCRIPT.unlink(missing_ok=True)
        return None
    DEFAULT_STARTUP_SCRIPT.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_STARTUP_SCRIPT.write_bytes(base64.b64decode(b64))
    DEFAULT_STARTUP_SCRIPT.chmod(0o755)
    return DEFAULT_STARTUP_SCRIPT


def _build_docker_run(
    env_file: Path,
    resp: dict,
    gpu_present: bool,
    startup_script: Path | None,
    overlay_hostname: str | None,
) -> list[str]:
    cmd = [
        "docker", "run", "-d",
        "--name", "lablink-client",
        "--restart", "unless-stopped",
        # Force a manifest check on every register so a republished image
        # tag (e.g. fixes pushed to ghcr.io for the same :0.0.8a0 stream)
        # actually lands on the BYO box; default `--pull missing` would
        # silently reuse the locally cached layers and ship the broken
        # bits forever. Costs one HEAD per register; layers that haven't
        # changed are not re-downloaded.
        "--pull", "always",
    ]
    if gpu_present:
        cmd += ["--gpus", "all"]
    if overlay_hostname is not None:
        # start.sh's `tailscaled` needs to create a TUN network interface
        # to route tailnet traffic to this container's own listening
        # sockets (6080/7070). Without these, tailscaled can't open
        # /dev/net/tun, dies immediately, and the subsequent `tailscale
        # up` fails with "failed to connect to local tailscaled; it
        # doesn't appear to be running". Gated on overlay_hostname since
        # lan_direct/allocator_proxied clients never invoke `tailscale up`.
        cmd += [
            "--cap-add", "NET_ADMIN",
            "--cap-add", "NET_RAW",
            "--device", "/dev/net/tun",
        ]
    # Mount path mirrors the AWS terraform/user_data mount so the client
    # start.sh finds the script at /docker_scripts/custom-startup.sh
    # regardless of provider. Skipped when the allocator returned no
    # script — docker would refuse the run otherwise (bind src must
    # exist), and start.sh already no-ops when the file is absent.
    if startup_script is not None:
        cmd += [
            "--mount",
            (
                f"type=bind,src={startup_script},"
                "dst=/docker_scripts/custom-startup.sh,ro"
            ),
            "-e",
            f"STARTUP_ON_ERROR={resp.get('startup_on_error', 'continue')}",
        ]
    # Publish 7070 (agent's /api/session/start) and 6080 (KasmVNC) on
    # the LAN IP so the allocator can reach them. `--network host` would
    # also do this on Linux, but on Docker Desktop (Windows/macOS) it
    # drops the container into the Docker VM's network instead of the
    # host's, leaving the ports unreachable from the LAN — the
    # allocator's password rotation just times out at the container's
    # :7070. Explicit `--publish` behaves the same on every platform.
    cmd += [
        "--publish", "7070:7070",
        "--publish", "6080:6080",
        "--env-file", str(env_file),
        resp["client_image"],
    ]
    return cmd


def _verify_gpu_runtime(console: Console) -> None:
    """Refuse to launch a GPU container on a host whose docker daemon
    uses the systemd cgroup driver.

    systemd reorganizes cgroups asynchronously (unit reloads, idle reaping,
    OOM events) and revokes GPU device permissions from running containers
    — nvidia-smi inside the client works at first, then fails after minutes,
    and check_gpu reports Unhealthy, which makes assignment skip the row
    (get_first_available_vm filters healthy='Unhealthy'). The AWS path's
    user_data.sh writes ``exec-opts: native.cgroupdriver=cgroupfs`` to
    avoid this; BYO operators have to set it themselves.

    Inspecting the daemon config (via ``docker info``) is the only reliable
    signal — a synchronous nvidia-smi smoke test would pass and then fail
    later, after the env file + container already exist.
    """
    if shutil.which("docker") is None:
        # _exec_docker will report this with the right error; skip here.
        return
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.CgroupDriver}}"],
            capture_output=True, text=True, check=True, timeout=10,
        )
        driver = result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        console.print(
            f"[red]Could not query docker daemon: {e}[/red]\n"
            "Verify docker is running and re-run "
            "`lablink client register --force`."
        )
        raise SystemExit(1) from e

    if driver == "cgroupfs":
        return

    # Heredoc terminator MUST be flush-left for bash to recognize it.
    # Rich indents block content; we render the shell snippet as a
    # plain code-fence-style block to keep the closing `JSON` at column 0
    # when the admin copy-pastes.
    snippet = (
        "sudo tee /etc/docker/daemon.json > /dev/null <<'JSON'\n"
        "{\n"
        '    "default-runtime": "nvidia",\n'
        '    "runtimes": {\n'
        '        "nvidia": {\n'
        '            "path": "nvidia-container-runtime",\n'
        '            "runtimeArgs": []\n'
        "        }\n"
        "    },\n"
        '    "exec-opts": ["native.cgroupdriver=cgroupfs"]\n'
        "}\n"
        "JSON\n"
        "sudo systemctl restart docker"
    )
    console.print(
        f"[red]Docker cgroup driver is '{driver}', not 'cgroupfs'.[/red]\n"
        "[bold]Your secrets file is saved.[/bold] After fixing daemon.json "
        "below, re-run [bold]lablink client register --force[/bold] to rotate the "
        "client secret and start the container.\n\n"
        "Why this matters: GPU access from the client container will fail "
        "after a few minutes (systemd reorganizes cgroups and revokes "
        "device permissions on running containers), check_gpu will report "
        "Unhealthy, and assignment will skip this client.\n\n"
        "[bold]Fix on the host (copy-paste exactly, the closing 'JSON' "
        "must be flush-left):[/bold]"
    )
    # Print snippet without Rich markup so indentation is preserved
    # verbatim — no leading whitespace inserted around the JSON terminator.
    print(snippet)
    raise SystemExit(1)


def _exec_docker(cmd: list[str], console: Console) -> None:
    if shutil.which("docker") is None:
        console.print(
            "[red]docker not found on PATH.[/red] Install Docker "
            "and re-run `lablink client register --force`."
        )
        raise SystemExit(1)
    # Remove any existing container with the target name. Quiet on
    # success (rm prints the container id); we don't care if it didn't
    # exist (rc != 0 in that case — ignored).
    subprocess.run(
        ["docker", "rm", "-f", "lablink-client"],
        capture_output=True,
        check=False,
    )
    console.print(
        f"Starting client container (image: {cmd[-1]}) …"
    )
    try:
        result = subprocess.run(cmd, check=False)
    except OSError as e:
        console.print(f"[red]Failed to exec docker: {e}[/red]")
        raise SystemExit(1) from e
    if result.returncode != 0:
        console.print(
            f"[red]docker run exited {result.returncode}.[/red] "
            "Check `docker logs lablink-client`."
        )
        raise SystemExit(result.returncode)
    console.print(
        "[green]Container running as lablink-client.[/green] "
        "View logs with: docker logs -f lablink-client"
    )


def _stop_existing_shipper(console: Console) -> None:
    """Terminate any running shipper recorded in the PID file.

    Called before spawning a new shipper so ``--force`` re-register doesn't
    leave the old shipper briefly tailing the replaced container and
    POSTing duplicates against the same hostname. The cmdline guard
    matches ``_shipper_alive`` so an unrelated PID-reused process is left
    alone.
    """
    if not PID_FILE.exists():
        return
    try:
        pid = int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        PID_FILE.unlink(missing_ok=True)
        return
    try:
        proc = psutil.Process(pid)
        cmdline = proc.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        PID_FILE.unlink(missing_ok=True)
        return
    if not any("lablink_cli.log_shipper" in arg for arg in cmdline):
        PID_FILE.unlink(missing_ok=True)
        return

    console.print(f"[dim]Stopping existing log shipper (PID {pid})...[/dim]")
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except psutil.TimeoutExpired:
        try:
            proc.kill()
        except psutil.NoSuchProcess:
            pass
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    # The shipper's SIGTERM handler removes the PID file; if we escalated
    # to SIGKILL the handler never ran, so clean up here.
    PID_FILE.unlink(missing_ok=True)


def _start_log_shipper(env_file: Path, console: Console) -> None:
    """Spawn the log shipper as a detached background process.

    The shipper survives this `register` invocation and runs until either
    the user does ``docker stop lablink-client`` (shipper's docker-logs
    subprocess exits and inspect reports missing) or the host reboots.
    """
    _stop_existing_shipper(console)

    log_dir = Path.home() / ".lablink"
    log_dir.mkdir(parents=True, exist_ok=True)
    shipper_log = log_dir / "log_shipper.log"
    # Append-mode handle for the detached child's stdout+stderr. The
    # shipper itself writes structured lines to this file via self_log();
    # the open handle here is just a safety net for any stray print.
    log_fd = open(shipper_log, "a", buffering=1)

    cmd = [sys.executable, "-m", "lablink_cli.log_shipper", str(env_file)]

    popen_kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": log_fd,
        "stderr": log_fd,
        "close_fds": True,
    }
    if os.name == "nt":
        # Windows: detach so the child survives the parent's exit.
        popen_kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS
            | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    else:
        # POSIX: new session detaches from the controlling TTY and parent
        # process group, matching nohup semantics.
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(cmd, **popen_kwargs)
    console.print(
        f"[green]Log shipping started (PID {proc.pid}).[/green] "
        f"Logs: {shipper_log}"
    )


def _shipper_alive() -> bool:
    """True iff a live log-shipper process matching our PID file exists.

    Two-stage check: PID present in PID file AND that PID belongs to a
    process whose cmdline mentions ``lablink_cli.log_shipper``. The
    cmdline guard prevents false positives from PID reuse after reboot.
    """
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        proc = psutil.Process(pid)
        cmdline = proc.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
    return any("lablink_cli.log_shipper" in arg for arg in cmdline)
