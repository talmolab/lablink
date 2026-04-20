"""Liveness heartbeat for the LabLink client VM.

Sends a small POST to the allocator every HEARTBEAT_INTERVAL_SECONDS so
the allocator can detect silent failures (dead container, broken network,
hung host, expired CRD token, out-of-band EC2 termination). The body
also carries a handful of cheap health signals for early warning.
"""

import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone

import hydra
import requests

from lablink_client_service.conf.structured_config import Config
from lablink_client_service.http_utils import (
    get_auth_headers,
    get_client_env,
    sanitize_url,
)
from lablink_client_service.logger_utils import CloudAndConsoleLogger


logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL_SECONDS = 30
HEARTBEAT_POST_TIMEOUT_SECONDS = 5
DOCKER_PROBE_TIMEOUT_SECONDS = 3
BOOT_ID_PATH = "/proc/sys/kernel/random/boot_id"


def read_boot_id() -> str | None:
    """Read the kernel-assigned per-boot UUID. Cached by the caller."""
    try:
        with open(BOOT_ID_PATH, "r") as f:
            return f.read().strip()
    except OSError as e:
        logger.warning(f"Could not read boot_id: {e}")
        return None


def sample_crd_active() -> bool:
    """Return True if the chrome-remote-desktop session is active."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "chrome-remote-desktop"],
            capture_output=True,
            timeout=2,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug(f"crd_active probe failed: {e}")
        return False


def sample_docker_healthy() -> bool:
    """Return True if `docker info` returns within the probe timeout."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=DOCKER_PROBE_TIMEOUT_SECONDS,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        logger.debug(f"docker_healthy probe failed: {e}")
        return False


def sample_disk_free_pct(path: str = "/") -> int:
    """Return integer percent of free space on the filesystem at `path`."""
    try:
        usage = shutil.disk_usage(path)
        if usage.total == 0:
            return 0
        return int((usage.free / usage.total) * 100)
    except OSError as e:
        logger.debug(f"disk_free_pct probe failed: {e}")
        return 0


def build_payload(vm_id: str | None, boot_id: str | None) -> dict:
    """Build the heartbeat JSON payload."""
    return {
        "vm_id": vm_id,
        "boot_id": boot_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "crd_active": sample_crd_active(),
        "docker_healthy": sample_docker_healthy(),
        "disk_free_pct": sample_disk_free_pct(),
    }


def send_heartbeat(
    base_url: str,
    headers: dict,
    payload: dict,
) -> None:
    """POST one heartbeat. Swallows network errors — never raises.

    Heartbeat integrity is in the allocator noticing when we *stop*
    sending. A failed individual POST is not worth crashing the client.
    """
    try:
        response = requests.post(
            f"{base_url}/api/heartbeat",
            json=payload,
            headers=headers,
            timeout=HEARTBEAT_POST_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            logger.debug(
                f"Heartbeat POST returned {response.status_code}: "
                f"{response.text[:200]}"
            )
    except requests.exceptions.RequestException as e:
        logger.debug(f"Heartbeat POST failed: {e}")


def run_heartbeat_loop(
    allocator_url: str,
    api_token: str = "",
    interval: int = HEARTBEAT_INTERVAL_SECONDS,
) -> None:
    """Long-running loop that sends a heartbeat every `interval` seconds."""
    logger.info("Starting heartbeat loop")
    base_url = sanitize_url(allocator_url)
    headers = {"Content-Type": "application/json"}
    headers.update(get_auth_headers(api_token))

    vm_id = os.getenv("VM_NAME")
    boot_id = read_boot_id()

    while True:
        payload = build_payload(vm_id=vm_id, boot_id=boot_id)
        send_heartbeat(base_url=base_url, headers=headers, payload=payload)
        time.sleep(interval)


@hydra.main(version_base=None, config_name="config")
def main(cfg: Config) -> None:
    global logger
    logger = CloudAndConsoleLogger(module_name="heartbeat")
    base_url, api_token, _ = get_client_env(cfg)
    run_heartbeat_loop(allocator_url=base_url, api_token=api_token)


if __name__ == "__main__":
    main()
