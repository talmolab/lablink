"""Automated VM reboot service.

Periodically checks for failed VMs and reboots them.

Assigned VMs get a warm reboot (plain ``sudo reboot``) so the container
survives via its ``--restart unless-stopped`` policy. Unassigned VMs get
a cold reboot (``cloud-init clean && sudo reboot``) that recreates the
container from scratch. Both paths fall back to EC2 stop/start (always
cold) when SSH is unavailable.

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

            # Max attempts exhausted: release the student's assignment
            # so they can be re-routed to a fresh VM. The VM is marked
            # 'error' and will not be retried until admin intervention.
            if vm["reboot_count"] >= self.max_attempts:
                logger.warning(
                    f"VM '{hostname}' exhausted reboot attempts "
                    f"({self.max_attempts}), releasing assignment"
                )
                try:
                    self.database.release_assignment(hostname)
                except Exception as e:
                    logger.error(
                        f"Failed to release assignment for "
                        f"'{hostname}': {e}"
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

            assigned = vm.get("useremail") is not None
            self._reboot_vm(hostname, assigned=assigned)

    def _ssh_reboot(self, ip: str, key_path: str, command: str) -> bool:
        """Send a reboot command to a VM via SSH.

        Args:
            ip: The public IP address of the instance.
            key_path: Path to the SSH private key file.
            command: The shell command to execute (e.g. "sudo reboot").

        Returns:
            True if the SSH command was sent successfully, False otherwise.
        """
        cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=10",
            "-i", key_path,
            f"ubuntu@{ip}",
            command,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
            # Exit code 0 = success, 255 = connection reset by reboot (expected)
            if result.returncode in (0, 255):
                logger.info(f"SSH reboot sent to {ip}: {command}")
                return True
            logger.warning(
                f"SSH reboot to {ip} returned exit code {result.returncode}: "
                f"{result.stderr.strip()}"
            )
            return False
        except subprocess.TimeoutExpired:
            logger.warning(f"SSH reboot to {ip} timed out")
            return False
        except Exception as e:
            logger.error(f"SSH reboot to {ip} failed: {e}")
            return False

    def _ssh_cold_reboot(self, ip: str, key_path: str) -> bool:
        """Cold reboot: destroy container, wipe cloud-init state, reboot.

        Used for unassigned VMs where we want a fresh container. The
        explicit ``docker rm -f`` ensures the container is gone before
        reboot, so the warm-reboot idempotence guard in ``user_data.sh``
        falls through to full provisioning on the next boot rather than
        no-op'ing. ``xargs -r`` skips the rm entirely when no containers
        exist, and ``;`` (not ``&&``) lets cloud-init clean + reboot
        proceed even if rm fails.
        """
        return self._ssh_reboot(
            ip,
            key_path,
            "sudo docker ps -aq | sudo xargs -r docker rm -f; "
            "sudo cloud-init clean && sudo reboot",
        )

    def _ssh_warm_reboot(self, ip: str, key_path: str) -> bool:
        """Warm reboot: plain OS reboot, container survives via restart policy.

        Used for assigned VMs to preserve the student's container state.
        cloud-init is NOT cleaned, so user_data does not re-run and the
        existing container (with --restart unless-stopped) auto-starts
        when the Docker daemon comes back.
        """
        return self._ssh_reboot(ip, key_path, "sudo reboot")

    def _reboot_vm(self, hostname: str, assigned: bool = False) -> bool:
        """Reboot a single VM by hostname.

        Tries two methods in order:
        1. SSH reboot — warm (plain reboot) for assigned VMs to preserve
           the container, cold (cloud-init clean + reboot) for unassigned.
        2. Stop/start — last resort. Always a cold reboot because
           cloud-init re-runs user_data on the next boot.

        Args:
            hostname: The VM hostname (matches EC2 Name tag).
            assigned: True if the VM has a student assigned (useremail set).
                Assigned VMs get a warm reboot to preserve the container.

        Returns:
            True if reboot was initiated, False otherwise.
        """
        reboot_type = "warm" if assigned else "cold"
        logger.info(
            f"Attempting {reboot_type} reboot for VM '{hostname}' "
            f"(assigned={assigned})"
        )

        # Look up EC2 instance ID by hostname (Name tag)
        instance_id = get_instance_id_by_name(
            hostname, region=self.region
        )
        if not instance_id:
            logger.error(
                f"Could not find EC2 instance for VM "
                f"'{hostname}', skipping reboot"
            )
            return False

        # 1) Try SSH reboot (warm or cold depending on assignment)
        ip = get_instance_public_ip(
            instance_id, region=self.region
        )
        if ip and self.terraform_dir:
            try:
                key_path = get_ssh_private_key(self.terraform_dir)
                ssh_reboot = (
                    self._ssh_warm_reboot if assigned
                    else self._ssh_cold_reboot
                )
                if ssh_reboot(ip, key_path):
                    self.database.record_reboot(hostname)
                    logger.info(
                        f"SSH {reboot_type} reboot initiated for VM "
                        f"'{hostname}' ({instance_id})"
                    )
                    return True
            except Exception as e:
                logger.warning(
                    f"Could not get SSH key for reboot: {e}"
                )

        # 2) Last resort: stop/start (always cold — cloud-init re-runs)
        logger.info(
            f"SSH unavailable for VM '{hostname}', falling back "
            f"to stop/start (cold reboot)"
        )
        success = stop_start_ec2_instance(
            instance_id, region=self.region
        )
        if success:
            self.database.record_reboot(hostname)
            logger.info(
                f"Stop/start initiated for VM '{hostname}' "
                f"({instance_id})"
            )
        else:
            logger.error(
                f"All reboot methods failed for VM "
                f"'{hostname}' ({instance_id})"
            )

        return success
