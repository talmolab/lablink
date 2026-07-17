"""Admin-session expiry sweep.

Periodically releases VMs an admin reserved for troubleshooting
(admin_reserve_vm) but never explicitly released, so an admin closing
the /desktop tab without clicking "Release" doesn't leave the VM stuck
out of the assignable pool forever. This is a fixed-duration safety net,
not activity-based idle detection — the allocator has no visibility
into whether the admin's VNC WebSocket is still open once nginx's
auth_request handshake has succeeded once.
"""

import logging
from threading import Event, Thread

from lablink_allocator_service.database import PostgresqlDatabase

logger = logging.getLogger(__name__)


class AdminSessionExpiryService:
    """Background service that releases expired admin VM reservations.

    Args:
        database: PostgresqlDatabase instance for querying/updating VM state.
        timeout_minutes: Age, in minutes, past which a reservation is
            considered expired and force-released.
        check_interval_seconds: How often to sweep for expired reservations.
    """

    def __init__(
        self,
        database: PostgresqlDatabase,
        timeout_minutes: int = 30,
        check_interval_seconds: int = 300,
    ):
        self.database = database
        self.timeout_minutes = timeout_minutes
        self.check_interval_seconds = check_interval_seconds
        self._stop_event = Event()
        self._thread = None

    def start(self):
        """Start the sweep thread."""
        self._stop_event.clear()
        self._thread = Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info(
            "Admin-session expiry service started (interval=%ss, timeout=%sm)",
            self.check_interval_seconds, self.timeout_minutes,
        )

    def stop(self):
        """Stop the sweep thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("Admin-session expiry service stopped")

    def _run(self):
        """Main loop that periodically sweeps for expired reservations."""
        while not self._stop_event.is_set():
            try:
                released = self.database.release_expired_admin_sessions(
                    self.timeout_minutes
                )
                if released:
                    logger.info("Released %d expired admin session(s)", released)
            except Exception as e:
                logger.error(
                    "Error in admin-session expiry sweep: %s", e, exc_info=True
                )
            self._stop_event.wait(self.check_interval_seconds)
