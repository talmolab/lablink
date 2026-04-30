"""View VM logs for a LabLink deployment."""

from __future__ import annotations

import base64
import json
import os
import ssl
import subprocess
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rich.console import Console

from lablink_allocator_service.conf.structured_config import Config

from lablink_cli.commands.utils import (
    get_allocator_url,
    get_deploy_dir,
    get_terraform_outputs,
    list_all_vms,
    resolve_admin_credentials,
)

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
    credentials = base64.b64encode(
        f"{admin_user}:{admin_pw}".encode()
    ).decode()

    req = Request(url, method="GET")
    req.add_header("Authorization", f"Basic {credentials}")
    req.add_header("Accept", "application/json")

    ctx = ssl.create_default_context()
    if ssl_provider == "self_signed":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    try:
        resp = urlopen(req, timeout=30, context=ctx)  # noqa: S310
        body = json.loads(resp.read().decode())
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
    from lablink_cli.auth.credentials import subprocess_env

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
            env=subprocess_env(),
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
    """Try SSH with terraform private key. Returns stdout/stderr or None."""
    ip = public_ip if public_ip != "—" else None
    if not ip:
        return None

    outputs = get_terraform_outputs(deploy_dir)
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
    using the terraform private key.
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
# Entry point
# ------------------------------------------------------------------
def run_logs(cfg: Config) -> None:
    """Launch the log viewer TUI."""
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

    vms = list_all_vms(cfg)
    if not vms:
        console.print(
            f"[red]No running VMs found for deployment "
            f"'{cfg.deployment_name}'.[/red]\n"
            "Run 'lablink deploy' and 'lablink launch-client' first."
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
