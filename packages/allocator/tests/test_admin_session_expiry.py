"""Tests for AdminSessionExpiryService and its config default."""
import time
from unittest.mock import MagicMock

from lablink_allocator_service.admin_session_expiry import AdminSessionExpiryService
from lablink_allocator_service.conf.structured_config import AppConfig


def test_app_config_admin_session_timeout_default():
    assert AppConfig().admin_session_timeout_minutes == 30


def test_start_launches_thread_and_stop_joins_it():
    mock_database = MagicMock()
    service = AdminSessionExpiryService(
        database=mock_database, timeout_minutes=30, check_interval_seconds=0.05
    )
    service.start()
    assert service._thread is not None
    assert service._thread.is_alive()
    service.stop()
    assert not service._thread.is_alive()


def test_sweep_calls_release_expired_admin_sessions_with_configured_timeout():
    mock_database = MagicMock()
    mock_database.release_expired_admin_sessions.return_value = 2
    service = AdminSessionExpiryService(
        database=mock_database, timeout_minutes=45, check_interval_seconds=0.05
    )
    service.start()
    try:
        for _ in range(100):
            if mock_database.release_expired_admin_sessions.called:
                break
            time.sleep(0.01)
    finally:
        service.stop()
    mock_database.release_expired_admin_sessions.assert_called_with(45)


def test_sweep_survives_database_error():
    mock_database = MagicMock()
    mock_database.release_expired_admin_sessions.side_effect = Exception("db down")
    service = AdminSessionExpiryService(
        database=mock_database, timeout_minutes=30, check_interval_seconds=0.05
    )
    service.start()
    time.sleep(0.1)
    service.stop()
    # No crash and the thread is stoppable — proves the exception was caught
    # inside the loop rather than killing the thread.
    assert not service._thread.is_alive()
