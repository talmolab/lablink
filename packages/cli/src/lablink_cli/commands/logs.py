"""View VM logs for a LabLink deployment."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError

from rich.console import Console
from rich.markup import escape

from lablink_allocator_service.conf.structured_config import Config

from lablink_cli import manual
from lablink_cli.api import authenticated_json_request
from lablink_cli.commands.utils import (
    AwsQueryError,
    get_allocator_url,
    get_deploy_dir,
    get_tofu_outputs,
    TofuError,
    list_all_vms,
    print_aws_error,
    resolve_admin_credentials,
)
from lablink_cli.docker import Docker, default_docker

console = Console()


# ------------------------------------------------------------------
# Log fetching — client VMs
# ------------------------------------------------------------------
def fetch_client_logs(
    allocator_url: str,
    hostname: str,
    admin_user: str,
    admin_pw: str,
    ssl_provider: str = "none",
) -> dict:
    """Fetch logs for a client VM from the allocator API."""
    url = f"{allocator_url}/api/vm-logs/{hostname}"

    try:
        body = authenticated_json_request(
            url, admin_user, admin_pw, ssl_provider=ssl_provider, timeout=30
        )
        return {
            "cloud_init_logs": body.get("cloud_init_logs"),
            "docker_logs": body.get("docker_logs"),
            "error": None,
        }
    except HTTPError as e:
        if e.code == 404:
            return {
                "cloud_init_logs": None,
                "docker_logs": None,
                "error": "VM not found in allocator database.",
            }
        elif e.code == 503:
            return {
                "cloud_init_logs": None,
                "docker_logs": None,
                "error": "VM is still initializing...",
            }
        elif e.code == 401:
            return {
                "cloud_init_logs": None,
                "docker_logs": None,
                "error": "Authentication failed. Check admin credentials.",
            }
        return {
            "cloud_init_logs": None,
            "docker_logs": None,
            "error": f"HTTP {e.code}: {e.reason}",
        }
    except URLError as e:
        return {
            "cloud_init_logs": None,
            "docker_logs": None,
            "error": f"Connection error: {e.reason}",
        }
    except Exception as e:
        return {
            "cloud_init_logs": None,
            "docker_logs": None,
            "error": f"Unexpected error: {e}",
        }


# ------------------------------------------------------------------
# Log fetching — allocator VM (via SSH)
# ------------------------------------------------------------------
def _ssh_via_instance_connect(
    instance_id: str,
    region: str,
    command: str,
) -> str | None:
    """Try SSH via ec2-instance-connect. Returns stdout or None."""
    try:
        result = subprocess.run(
            [
                "aws",
                "ec2-instance-connect",
                "ssh",
                "--instance-id",
                instance_id,
                "--os-user",
                "ubuntu",
                "--connection-type",
                "eice",
                "--region",
                region,
                "--",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _ssh_via_private_key(
    public_ip: str,
    command: str,
    deploy_dir: Path,
) -> str | None:
    """Try SSH with the OpenTofu-provisioned private key.

    Returns stdout/stderr or None.
    """
    ip = public_ip if public_ip != "—" else None
    if not ip:
        return None

    try:
        outputs = get_tofu_outputs(deploy_dir)
    except TofuError as e:
        console.print(
            f"  [yellow]Could not read the SSH key:[/yellow] {escape(str(e))}"
        )
        return None
    private_key_pem = outputs.get("private_key_pem", "")
    if not private_key_pem:
        return None

    key_file = None
    try:
        key_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".pem", delete=False
        )
        key_file.write(private_key_pem)
        key_file.close()
        os.chmod(key_file.name, 0o600)

        result = subprocess.run(
            [
                "ssh",
                "-i",
                key_file.name,
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "ConnectTimeout=10",
                f"ubuntu@{ip}",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return result.stdout
        return (
            result.stderr
            or f"SSH exited with code {result.returncode}"
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    finally:
        if key_file and os.path.exists(key_file.name):
            os.unlink(key_file.name)


def _run_ssh_command(
    instance_id: str,
    public_ip: str,
    region: str,
    command: str,
    deploy_dir: Path,
) -> str | None:
    """Run a command on the allocator via SSH.

    Tries ec2-instance-connect first, then falls back to direct SSH
    using the OpenTofu-provisioned private key.
    """
    return _ssh_via_instance_connect(
        instance_id, region, command
    ) or _ssh_via_private_key(public_ip, command, deploy_dir)


_LOG_DELIMITER = "===LABLINK_LOG_SEPARATOR==="

_COMBINED_LOG_CMD = (
    "cat /var/log/cloud-init-output.log 2>/dev/null;"
    f" echo '{_LOG_DELIMITER}';"
    " sudo docker logs $(sudo docker ps -q | head -1)"
    " --tail 2000 2>&1"
)


def fetch_allocator_logs(
    instance_id: str,
    public_ip: str,
    region: str,
    deploy_dir: Path,
) -> dict:
    """Fetch cloud-init and docker logs from the allocator EC2 instance."""
    output = _run_ssh_command(
        instance_id,
        public_ip,
        region,
        _COMBINED_LOG_CMD,
        deploy_dir,
    )

    if output is None:
        return {
            "cloud_init_logs": None,
            "docker_logs": None,
            "error": (
                "Could not SSH into allocator. "
                "Ensure ec2-instance-connect is available or "
                "port 22 is open."
            ),
        }

    parts = output.split(_LOG_DELIMITER, 1)
    cloud_init = parts[0].strip() or None
    docker = parts[1].strip() if len(parts) > 1 else None

    return {
        "cloud_init_logs": cloud_init,
        "docker_logs": docker,
        "error": None,
    }


# ------------------------------------------------------------------
# Log fetching — manual-provider allocator (local docker container)
# ------------------------------------------------------------------
_MANUAL_ALLOCATOR_TAIL = 2000


def fetch_manual_allocator_logs(*, docker: Docker | None = None) -> dict:
    """Snapshot the local lablink-allocator container's logs.

    Mirrors :func:`fetch_allocator_logs` / :func:`fetch_client_logs`
    contract (cloud_init_logs, docker_logs, error keys) so the TUI can
    treat manual + AWS uniformly.
    """
    docker = docker or default_docker()
    result = docker.logs(
        "lablink-allocator", tail=_MANUAL_ALLOCATOR_TAIL, timeout=30
    )
    if not result.ok:
        stderr = result.stderr.strip()
        if "No such container" in stderr:
            err = (
                "lablink-allocator container is not running. "
                "Run `lablink deploy` to start it."
            )
        else:
            err = stderr or f"docker logs exited {result.returncode}"
        return {"cloud_init_logs": None, "docker_logs": None, "error": err}

    # docker writes the container's own stdout to its stdout, stderr to its
    # stderr — merge them so the TUI shows everything chronologically.
    combined = (result.stdout or "") + (result.stderr or "")
    return {
        "cloud_init_logs": None,
        "docker_logs": combined.strip() or None,
        "error": None,
    }


# ------------------------------------------------------------------
# Log fetching — external-runtime allocator (no local docker container)
# ------------------------------------------------------------------
def fetch_external_allocator_logs(
    *,
    allocator_url: str,
    admin_user: str,
    admin_password: str,
    ssl_provider: str = "none",
) -> dict:
    """Snapshot an externally-run allocator's own logs over HTTP.

    External-runtime deployments (``lablink deploy --render-only``) have
    no local ``lablink-allocator`` container to ``docker logs``; the
    allocator serves the same content at ``GET /api/allocator-logs``
    (admin basic-auth, redacted tail of /var/log/lablink/allocator.log).
    Routed through :func:`authenticated_json_request` — the same helper
    :func:`fetch_client_logs` uses — rather than a bare ``requests.get``:
    Cloudflare-proxied allocators (this feature's own topology) return
    HTTP 403 for the default urllib/requests User-Agent, and that helper
    is what sends the CLI's product UA instead (see api.py). Mirrors
    :func:`fetch_manual_allocator_logs`'s contract
    (cloud_init_logs / docker_logs / error keys).
    """
    url = f"{allocator_url.rstrip('/')}/api/allocator-logs"
    try:
        body = authenticated_json_request(
            url, admin_user, admin_password, ssl_provider=ssl_provider, timeout=30
        )
        return {
            "cloud_init_logs": body.get("cloud_init_logs"),
            "docker_logs": body.get("docker_logs"),
            "error": body.get("error"),
        }
    except (HTTPError, URLError, json.JSONDecodeError) as e:
        return {
            "cloud_init_logs": None,
            "docker_logs": None,
            "error": (
                f"Could not fetch allocator logs from {url}: {e} "
                "(is the platform workload running?)"
            ),
        }


# ------------------------------------------------------------------
# Manual-provider TUI launcher
# ------------------------------------------------------------------
def _run_logs_manual(
    cfg: Config, *, workdir_root: Path | None = None
) -> None:
    """Discover BYO clients via /api/v1/clients and launch the TUI.

    The TUI shows the local allocator container plus every registered
    BYO client. Client logs come from /api/vm-logs/<hostname> (populated
    by the manual-client log shipper). The allocator entry is fetched via
    local ``docker logs lablink-allocator`` instead of SSH — except for an
    external-runtime deployment (``lablink deploy --render-only``), which
    has no local container at all; its allocator entry is fetched over
    HTTP from its own public URL instead (see ``fetch_external_allocator_logs``).

    `workdir_root` overrides the default compose root (used by tests).
    """
    workdir = manual.workdir(cfg, workdir_root)

    creds = manual.admin_credentials(cfg, workdir)
    if not creds:
        console.print(
            "[red]Could not resolve allocator admin credentials.[/red]\n"
            f"Run `lablink deploy` first (expected workdir: {workdir})."
        )
        raise SystemExit(1)
    admin_user, admin_pw = creds

    runtime = manual.deployment_runtime(workdir)
    if runtime == "external":
        # No local container/port to fall back to — the allocator only
        # exists at the public URL staged by `lablink deploy --render-only`
        # (same canonical-URL file `lablink status` reads).
        allocator_url = manual.public_url(workdir)
        if not allocator_url:
            console.print(
                "[red]Could not determine the external allocator's public "
                "URL.[/red]\n"
                f"Expected one recorded under {workdir} — re-run `lablink "
                "deploy --render-only` or check the platform workload."
            )
            raise SystemExit(1)
    else:
        allocator_url = manual.base_url(cfg)

    console.print(
        "[dim]Fetching registered BYO clients from the allocator...[/dim]"
    )
    # allocator_url is localhost for a compose stack (registered_clients'
    # default) and the recorded public URL for an external runtime.
    clients, err = manual.registered_clients(
        cfg, admin_user, admin_pw, base=allocator_url
    )
    if clients is None:
        console.print(
            f"[red]Failed to list clients:[/red] {err}\n"
            "Is the allocator running? Try `lablink status`."
        )
        raise SystemExit(1)

    # Synthetic VM list: allocator first, then clients. Shapes match the
    # AWS-mode dicts (name, type, vm_type, public_ip, state) so LogsApp +
    # VMListItem work uniformly. The allocator is implicitly "running"
    # here — manual.registered_clients just succeeded against it.
    vms: list[dict] = [
        {
            "name": "lablink-allocator",
            "type": "compose",
            "vm_type": "allocator",
            "public_ip": "localhost",
            "state": "running",
        }
    ]
    for c in clients:
        hostname = c.get("hostname") or "-"
        vms.append({
            "name": hostname,
            "type": "byo",
            "vm_type": "client",
            "public_ip": c.get("lan_ip") or "—",
            "state": c.get("status") or "unknown",
        })

    from lablink_cli.tui.logs_viewer import LogsApp

    app = LogsApp(
        cfg=cfg,
        vms=vms,
        allocator_url=allocator_url,
        admin_user=admin_user,
        admin_pw=admin_pw,
        deploy_dir=workdir,
        manual=True,
        runtime=runtime,
    )
    app.run()


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
def run_logs(cfg: Config) -> None:
    """Launch the log viewer TUI."""
    if getattr(cfg, "provider", "aws") == "manual":
        _run_logs_manual(cfg)
        return

    deploy_dir = get_deploy_dir(cfg)

    if not deploy_dir.exists():
        console.print(
            f"[red]No deployment found for "
            f"'{cfg.deployment_name}'.[/red]\n"
            "Run 'lablink deploy' first."
        )
        raise SystemExit(1)

    console.print(
        f"[dim]Discovering VMs for deployment "
        f"'{cfg.deployment_name}' ({cfg.environment})...[/dim]"
    )

    try:
        vms = list_all_vms(cfg)
    except AwsQueryError as e:
        print_aws_error(e, prefix="Could not list VMs")
        raise SystemExit(1) from e

    if not vms:
        console.print(
            f"[red]No running VMs found for deployment "
            f"'{cfg.deployment_name}'.[/red]\n"
            "Run 'lablink deploy' and 'lablink client launch' first."
        )
        raise SystemExit(1)

    allocator_url = get_allocator_url(cfg)
    if not allocator_url:
        console.print(
            "[yellow]Warning: Could not determine allocator URL. "
            "Client VM logs will not be available.[/yellow]"
        )

    admin_user, admin_pw = resolve_admin_credentials(cfg)

    from lablink_cli.tui.logs_viewer import LogsApp

    app = LogsApp(
        cfg=cfg,
        vms=vms,
        allocator_url=allocator_url,
        admin_user=admin_user,
        admin_pw=admin_pw,
        deploy_dir=deploy_dir,
    )
    app.run()
