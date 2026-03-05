"""Automated VM reboot service.

Periodically checks for failed VMs and reboots them via SSH hard reboot
(cloud-init clean + reboot) with stop/start fallback.
Respects cooldown periods and maximum reboot attempt limits.
"""

import logging
import subprocess
from datetime import datetime, timezone
from threading import Thread, Event

from lablink_allocator_service.database import PostgresqlDatabase
from lablink_allocator_service.utils.aws_utils import (
    get_instance_id_by_name,
    get_instance_public_ip,
    stop_start_ec2_instance,
)
from lablink_allocator_service.utils.terraform_utils import get_ssh_private_key

logger = logging.getLogger(__name__)


class AutoRebootService:
    """Background service that monitors for failed VMs and reboots them.

    Args:
        database: PostgresqlDatabase instance for querying/updating VM state.
        region: AWS region where VMs are deployed.
        terraform_dir: Path to the Terraform directory (for SSH key retrieval).
        max_attempts: Maximum reboot attempts per VM before giving up.
        cooldown_seconds: Minimum seconds between reboots of the same VM.
        check_interval_seconds: How often to check for failed VMs.
    """

    def __init__(
        self,
        database: PostgresqlDatabase,
        region: str = "us-west-2",
        terraform_dir: str = "",
        max_attempts: int = 3,
        cooldown_seconds: int = 300,
        check_interval_seconds: int = 60,
    ):
        self.database = database
        self.region = region
        self.terraform_dir = terraform_dir
        self.max_attempts = max_attempts
        self.cooldown_seconds = cooldown_seconds
        self.check_interval_seconds = check_interval_seconds
        self._stop_event = Event()
        self._thread = None

    def start(self):
        """Start the auto-reboot monitoring thread."""
        self.database.ensure_reboot_columns()
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(
            f"Auto-reboot service started (interval={self.check_interval_seconds}s, "
            f"max_attempts={self.max_attempts}, cooldown={self.cooldown_seconds}s)"
        )

    def stop(self):
        """Stop the auto-reboot monitoring thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Auto-reboot service stopped")

    def _run(self):
        """Main loop that periodically checks for failed VMs."""
        while not self._stop_event.is_set():
            try:
                self._check_and_reboot()
            except Exception as e:
                logger.error(f"Error in auto-reboot check: {e}", exc_info=True)
            self._stop_event.wait(self.check_interval_seconds)

    def _check_and_reboot(self):
        """Check for failed VMs and reboot eligible ones."""
        failed_vms = self.database.get_failed_vms()
        if not failed_vms:
            return

        now = datetime.now(timezone.utc)

        for vm in failed_vms:
            hostname = vm["hostname"]

            # Check max attempts
            if vm["reboot_count"] >= self.max_attempts:
                logger.debug(
                    f"VM '{hostname}' has reached max reboot attempts "
                    f"({self.max_attempts}), skipping"
                )
                continue

            # Check cooldown
            last_reboot = vm["last_reboot_time"]
            if last_reboot is not None:
                if last_reboot.tzinfo is None:
                    last_reboot = last_reboot.replace(tzinfo=timezone.utc)
                elapsed = (now - last_reboot).total_seconds()
                if elapsed < self.cooldown_seconds:
                    logger.debug(
                        f"VM '{hostname}' is in cooldown "
                        f"({elapsed:.0f}s < {self.cooldown_seconds}s), skipping"
                    )
                    continue

            self._reboot_vm(hostname)

    def _ssh_hard_reboot(self, ip: str, key_path: str) -> bool:
        """Perform a hard reboot via SSH (cloud-init clean + reboot).

        Args:
            ip: The public IP address of the instance.
            key_path: Path to the SSH private key file.

        Returns:
            True if the SSH reboot command was sent successfully, False otherwise.
        """
        cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            "-i", key_path,
            f"ubuntu@{ip}",
            "sudo cloud-init clean && sudo reboot",
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            # Exit code 0 = success, 255 = connection reset by reboot (expected)
            if result.returncode in (0, 255):
                logger.info(f"SSH hard reboot sent to {ip}")
                return True
            logger.warning(
                f"SSH hard reboot to {ip} returned exit code {result.returncode}: "
                f"{result.stderr.strip()}"
            )
            return False
        except subprocess.TimeoutExpired:
            logger.warning(f"SSH hard reboot to {ip} timed out")
            return False
        except Exception as e:
            logger.error(f"SSH hard reboot to {ip} failed: {e}")
            return False

    def _reboot_vm(self, hostname: str) -> bool:
        """Reboot a single VM by hostname using SSH hard reboot with fallback.

        Flow:
        1. Look up EC2 instance ID by hostname
        2. Try SSH hard reboot (cloud-init clean + reboot) — re-runs user_data
        3. If SSH fails, fall back to stop/start (restarts VM but does NOT
           re-run user_data since cloud-init state persists on EBS)

        Args:
            hostname: The VM hostname (matches EC2 Name tag).

        Returns:
            True if reboot was initiated, False otherwise.
        """
        logger.info(f"Attempting to reboot VM '{hostname}'")

        # Look up EC2 instance ID by hostname (Name tag)
        instance_id = get_instance_id_by_name(hostname, region=self.region)
        if not instance_id:
            logger.error(
                f"Could not find EC2 instance for VM '{hostname}', "
                f"skipping reboot"
            )
            return False

        # Try SSH hard reboot first (clears cloud-init → user_data re-runs)
        ip = get_instance_public_ip(instance_id, region=self.region)
        ssh_success = False

        if ip and self.terraform_dir:
            try:
                key_path = get_ssh_private_key(self.terraform_dir)
                ssh_success = self._ssh_hard_reboot(ip, key_path)
            except Exception as e:
                logger.warning(
                    f"Could not get SSH key for hard reboot: {e}"
                )

        if ssh_success:
            self.database.record_reboot(hostname)
            logger.info(
                f"SSH hard reboot initiated for VM '{hostname}' "
                f"(instance {instance_id})"
            )
            return True

        # Fallback: stop/start restarts the VM but does NOT clear
        # cloud-init state, so user_data.sh will not re-run. This is
        # a best-effort restart for hung processes, OOM, etc.
        if not ip:
            logger.info(
                f"No public IP for VM '{hostname}', "
                f"falling back to stop/start"
            )
        else:
            logger.info(
                f"SSH hard reboot failed for VM '{hostname}', "
                f"falling back to stop/start"
            )
        success = stop_start_ec2_instance(
            instance_id, region=self.region
        )
        if success:
            self.database.record_reboot(hostname)
            logger.info(
                f"Stop/start initiated for VM '{hostname}' "
                f"(instance {instance_id}). Note: user_data.sh "
                f"will NOT re-run (cloud-init state persists)."
            )
        else:
            logger.error(
                f"All reboot methods failed for VM '{hostname}' "
                f"(instance {instance_id})"
            )

        return success
