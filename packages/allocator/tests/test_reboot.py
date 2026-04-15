"""Tests for the automated VM reboot system."""

import pytest
from unittest.mock import MagicMock, patch, ANY
from datetime import datetime, timezone, timedelta

# Mock psycopg2 before importing modules
mock_psycopg2 = MagicMock()
mock_psycopg2.IntegrityError = type("IntegrityError", (Exception,), {})

with patch.dict(
    "sys.modules",
    {"psycopg2": mock_psycopg2, "psycopg2.extensions": MagicMock()},
):
    from lablink_allocator_service.database import PostgresqlDatabase
    import lablink_allocator_service.reboot as reboot_mod
    AutoRebootService = reboot_mod.AutoRebootService


@pytest.fixture
def mock_db_connection():
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor_context = MagicMock()
    mock_cursor_context.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor_context.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor_context
    mock_psycopg2.connect.return_value = mock_conn
    return mock_conn, mock_cursor


@pytest.fixture
def db_instance(mock_db_connection):
    db = PostgresqlDatabase(
        dbname="testdb",
        user="testuser",
        password="testpassword",
        host="localhost",
        port=5432,
        table_name="vms",
        message_channel="test_channel",
    )
    db.conn, db.cursor = mock_db_connection
    return db


# --- Database method tests ---


def test_update_vm_status_rebooting(db_instance):
    """Test that 'rebooting' is a valid VM status."""
    db_instance.update_vm_status("vm-1", "rebooting")
    db_instance.cursor.execute.assert_called_with(ANY, ("vm-1", "rebooting"))
    db_instance.conn.commit.assert_called_once()


def test_get_failed_vms(db_instance):
    """Test retrieving failed VMs."""
    db_instance.cursor.fetchall.return_value = [
        ("vm-1", "error", None, 0, None),
        ("vm-2", "running", "Unhealthy", 1, datetime(2025, 1, 1)),
    ]

    result = db_instance.get_failed_vms()

    assert len(result) == 2
    assert result[0]["hostname"] == "vm-1"
    assert result[0]["status"] == "error"
    assert result[0]["reboot_count"] == 0
    assert result[1]["hostname"] == "vm-2"
    assert result[1]["healthy"] == "Unhealthy"
    assert result[1]["reboot_count"] == 1


def test_get_failed_vms_empty(db_instance):
    """Test retrieving failed VMs when none are failed."""
    db_instance.cursor.fetchall.return_value = []
    result = db_instance.get_failed_vms()
    assert result == []


def test_get_failed_vms_error(db_instance, caplog):
    """Test error handling in get_failed_vms."""
    db_instance.cursor.execute.side_effect = Exception("DB error")
    result = db_instance.get_failed_vms()
    assert result == []
    assert "Failed to get failed VMs" in caplog.text


def test_get_failed_vms_includes_stale_initializing(db_instance):
    """Test that stale initializing VMs are included in failed VMs query."""
    db_instance.cursor.fetchall.return_value = [
        ("vm-stale", "initializing", None, 0, None),
    ]

    result = db_instance.get_failed_vms(stale_initializing_minutes=15)

    assert len(result) == 1
    assert result[0]["hostname"] == "vm-stale"
    assert result[0]["status"] == "initializing"

    # Verify the query includes the stale initializing clause
    query = db_instance.cursor.execute.call_args[0][0]
    assert "initializing" in query
    assert "INTERVAL" in query
    assert "15 minutes" in query


def test_get_failed_vms_default_stale_initializing_is_25_minutes(db_instance):
    """Default stale_initializing_minutes is 25 to accommodate custom startups.

    user_data.sh no longer prematurely reports status='running' right
    after docker run; readiness is now reported by start.sh after
    custom-startup.sh finishes. The legitimate 'initializing' window
    can therefore span the full duration of tutorial-data downloads
    and other custom-startup work.
    """
    db_instance.cursor.fetchall.return_value = []
    db_instance.get_failed_vms()  # no explicit arguments

    query = db_instance.cursor.execute.call_args[0][0]
    assert "25 minutes" in query


def test_get_failed_vms_includes_stuck_rebooting(db_instance):
    """Test that VMs stuck in rebooting state are re-eligible."""
    db_instance.cursor.fetchall.return_value = [
        ("vm-stuck", "rebooting", None, 1, datetime(2025, 1, 1)),
    ]

    result = db_instance.get_failed_vms(stale_rebooting_minutes=10)

    assert len(result) == 1
    assert result[0]["hostname"] == "vm-stuck"
    assert result[0]["status"] == "rebooting"

    # Verify the query includes the stale rebooting clause
    query = db_instance.cursor.execute.call_args[0][0]
    assert "rebooting" in query
    assert "last_reboot_time" in query
    assert "10 minutes" in query


def test_record_reboot(db_instance):
    """Test recording a reboot attempt."""
    db_instance.record_reboot("vm-1")
    db_instance.cursor.execute.assert_called_with(ANY, ("vm-1",))
    db_instance.conn.commit.assert_called_once()

    # Verify CRD-session fields are cleared but the student's assignment
    # is preserved (so the student keeps their VM slot across reboots).
    query = db_instance.cursor.execute.call_args[0][0]
    assert "crdcommand = NULL" in query
    assert "pin = NULL" in query
    assert "useremail = NULL" not in query
    assert "status = 'rebooting'" in query
    assert "reboot_count" in query


def test_record_reboot_error(db_instance, caplog):
    """Test error handling in record_reboot."""
    db_instance.cursor.execute.side_effect = Exception("DB error")
    with pytest.raises(Exception, match="DB error"):
        db_instance.record_reboot("vm-1")
    db_instance.conn.rollback.assert_called_once()


def test_release_assignment(db_instance):
    """Test releasing a VM's assignment when reboot attempts are exhausted."""
    db_instance.release_assignment("vm-1")
    db_instance.cursor.execute.assert_called_with(ANY, ("vm-1",))
    db_instance.conn.commit.assert_called_once()

    query = db_instance.cursor.execute.call_args[0][0]
    assert "useremail = NULL" in query
    assert "crdcommand = NULL" in query
    assert "pin = NULL" in query
    assert "status = 'error'" in query
    # reboot_count is intentionally preserved for diagnostics
    assert "reboot_count" not in query


def test_release_assignment_error(db_instance, caplog):
    """Test error handling in release_assignment."""
    db_instance.cursor.execute.side_effect = Exception("DB error")
    with pytest.raises(Exception, match="DB error"):
        db_instance.release_assignment("vm-1")
    db_instance.conn.rollback.assert_called_once()
    assert "Failed to release assignment for" in caplog.text


def test_get_reboot_info(db_instance):
    """Test getting reboot info for a VM."""
    last_reboot = datetime(2025, 1, 1, 12, 0, 0)
    db_instance.cursor.fetchone.return_value = (2, last_reboot)

    result = db_instance.get_reboot_info("vm-1")

    assert result["reboot_count"] == 2
    assert result["last_reboot_time"] == last_reboot


def test_get_reboot_info_not_found(db_instance):
    """Test getting reboot info for non-existent VM."""
    db_instance.cursor.fetchone.return_value = None
    result = db_instance.get_reboot_info("vm-nonexistent")
    assert result is None


def test_get_reboot_info_error(db_instance, caplog):
    """Test error handling in get_reboot_info."""
    db_instance.cursor.execute.side_effect = Exception("DB error")
    result = db_instance.get_reboot_info("vm-1")
    assert result is None
    assert "Failed to get reboot info" in caplog.text


def test_ensure_reboot_columns(db_instance):
    """Test that ensure_reboot_columns adds columns."""
    db_instance.ensure_reboot_columns()
    assert db_instance.cursor.execute.call_count == 2
    calls = [str(c) for c in db_instance.cursor.execute.call_args_list]
    assert any("reboot_count" in c for c in calls)
    assert any("last_reboot_time" in c for c in calls)


# --- AutoRebootService tests ---


def test_ssh_hard_reboot_success(monkeypatch):
    """Test successful SSH hard reboot."""
    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        terraform_dir="/tmp/terraform",
    )

    mock_run = MagicMock()
    mock_run.return_value.returncode = 0
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._ssh_hard_reboot("1.2.3.4", "/tmp/key.pem")

    assert result is True
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "ssh" in cmd
    assert "ubuntu@1.2.3.4" in cmd
    assert "sudo cloud-init clean && sudo reboot" in cmd


def test_ssh_hard_reboot_exit_255(monkeypatch):
    """Test SSH hard reboot with exit code 255 (connection reset by reboot)."""
    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        terraform_dir="/tmp/terraform",
    )

    mock_run = MagicMock()
    mock_run.return_value.returncode = 255
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._ssh_hard_reboot("1.2.3.4", "/tmp/key.pem")
    assert result is True


def test_ssh_hard_reboot_timeout(monkeypatch):
    """Test SSH hard reboot timeout."""
    import subprocess

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        terraform_dir="/tmp/terraform",
    )

    mock_run = MagicMock(side_effect=subprocess.TimeoutExpired("ssh", 30))
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._ssh_hard_reboot("1.2.3.4", "/tmp/key.pem")
    assert result is False


def test_ssh_hard_reboot_failure(monkeypatch):
    """Test SSH hard reboot with non-zero exit code."""
    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        terraform_dir="/tmp/terraform",
    )

    mock_run = MagicMock()
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Connection refused"
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._ssh_hard_reboot("1.2.3.4", "/tmp/key.pem")
    assert result is False


def test_reboot_vm_ssh_success(monkeypatch):
    """Test successful VM reboot via SSH."""
    monkeypatch.setattr(reboot_mod, "get_instance_id_by_name", lambda *a, **kw: "i-12345")
    monkeypatch.setattr(reboot_mod, "get_instance_public_ip", lambda *a, **kw: "1.2.3.4")
    monkeypatch.setattr(reboot_mod, "get_ssh_private_key", lambda *a, **kw: "/tmp/key.pem")

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        terraform_dir="/tmp/terraform",
    )

    mock_run = MagicMock()
    mock_run.return_value.returncode = 0
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._reboot_vm("vm-1")

    assert result is True
    mock_db.record_reboot.assert_called_once_with("vm-1")


def test_reboot_vm_ssh_fails_stop_start_succeeds(monkeypatch):
    """Test fallback to stop/start when SSH fails."""
    monkeypatch.setattr(reboot_mod, "get_instance_id_by_name", lambda *a, **kw: "i-12345")
    monkeypatch.setattr(reboot_mod, "get_instance_public_ip", lambda *a, **kw: "1.2.3.4")
    monkeypatch.setattr(reboot_mod, "get_ssh_private_key", lambda *a, **kw: "/tmp/key.pem")
    monkeypatch.setattr(reboot_mod, "stop_start_ec2_instance", lambda *a, **kw: True)

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        terraform_dir="/tmp/terraform",
    )

    # SSH fails with exit code 1
    mock_run = MagicMock()
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Connection refused"
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._reboot_vm("vm-1")

    assert result is True
    mock_db.record_reboot.assert_called_once_with("vm-1")


def test_reboot_vm_no_ip_stop_start_succeeds(monkeypatch):
    """Test stop/start fallback when no public IP available."""
    monkeypatch.setattr(reboot_mod, "get_instance_id_by_name", lambda *a, **kw: "i-12345")
    monkeypatch.setattr(reboot_mod, "get_instance_public_ip", lambda *a, **kw: None)
    monkeypatch.setattr(reboot_mod, "stop_start_ec2_instance", lambda *a, **kw: True)

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        terraform_dir="/tmp/terraform",
    )

    result = service._reboot_vm("vm-1")

    assert result is True
    mock_db.record_reboot.assert_called_once_with("vm-1")


def test_reboot_vm_all_methods_fail(monkeypatch):
    """Test when SSH and stop/start both fail."""
    monkeypatch.setattr(reboot_mod, "get_instance_id_by_name", lambda *a, **kw: "i-12345")
    monkeypatch.setattr(reboot_mod, "get_instance_public_ip", lambda *a, **kw: "1.2.3.4")
    monkeypatch.setattr(reboot_mod, "get_ssh_private_key", lambda *a, **kw: "/tmp/key.pem")
    monkeypatch.setattr(reboot_mod, "stop_start_ec2_instance", lambda *a, **kw: False)

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        terraform_dir="/tmp/terraform",
    )

    # SSH fails
    mock_run = MagicMock()
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Connection refused"
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._reboot_vm("vm-1")

    assert result is False
    mock_db.record_reboot.assert_not_called()


def test_reboot_vm_instance_not_found(monkeypatch):
    """Test reboot when EC2 instance not found."""
    monkeypatch.setattr(reboot_mod, "get_instance_id_by_name", lambda *a, **kw: None)

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        terraform_dir="/tmp/terraform",
    )

    result = service._reboot_vm("vm-nonexistent")

    assert result is False
    mock_db.record_reboot.assert_not_called()


@patch.object(AutoRebootService, "_reboot_vm")
def test_check_and_reboot_releases_on_max_attempts(mock_reboot):
    """Test that VMs exceeding max attempts have their assignment released."""
    mock_db = MagicMock()
    mock_db.get_failed_vms.return_value = [
        {
            "hostname": "vm-1",
            "status": "error",
            "healthy": None,
            "reboot_count": 3,
            "last_reboot_time": None,
        }
    ]

    service = AutoRebootService(
        database=mock_db,
        max_attempts=3,
        cooldown_seconds=300,
        terraform_dir="/tmp/terraform",
    )
    service._check_and_reboot()

    mock_reboot.assert_not_called()
    mock_db.release_assignment.assert_called_once_with("vm-1")


@patch.object(AutoRebootService, "_reboot_vm")
def test_check_and_reboot_below_max_does_not_release(mock_reboot):
    """Test that VMs below max_attempts are not released."""
    mock_db = MagicMock()
    mock_db.get_failed_vms.return_value = [
        {
            "hostname": "vm-1",
            "status": "error",
            "healthy": None,
            "reboot_count": 1,
            "last_reboot_time": None,
        }
    ]

    service = AutoRebootService(
        database=mock_db,
        max_attempts=3,
        cooldown_seconds=300,
        terraform_dir="/tmp/terraform",
    )
    service._check_and_reboot()

    mock_reboot.assert_called_once_with("vm-1")
    mock_db.release_assignment.assert_not_called()


@patch.object(AutoRebootService, "_reboot_vm")
def test_check_and_reboot_respects_cooldown(mock_reboot):
    """Test that VMs in cooldown are skipped."""
    mock_db = MagicMock()
    recent_reboot = datetime.now(timezone.utc) - timedelta(seconds=60)
    mock_db.get_failed_vms.return_value = [
        {
            "hostname": "vm-1",
            "status": "error",
            "healthy": None,
            "reboot_count": 1,
            "last_reboot_time": recent_reboot,
        }
    ]

    service = AutoRebootService(
        database=mock_db,
        max_attempts=3,
        cooldown_seconds=300,
        terraform_dir="/tmp/terraform",
    )
    service._check_and_reboot()

    mock_reboot.assert_not_called()


@patch.object(AutoRebootService, "_reboot_vm")
def test_check_and_reboot_triggers_reboot(mock_reboot):
    """Test that eligible failed VMs are rebooted."""
    mock_db = MagicMock()
    mock_db.get_failed_vms.return_value = [
        {
            "hostname": "vm-1",
            "status": "error",
            "healthy": None,
            "reboot_count": 0,
            "last_reboot_time": None,
        }
    ]

    service = AutoRebootService(
        database=mock_db,
        max_attempts=3,
        cooldown_seconds=300,
        terraform_dir="/tmp/terraform",
    )
    service._check_and_reboot()

    mock_reboot.assert_called_once_with("vm-1")


@patch.object(AutoRebootService, "_reboot_vm")
def test_check_and_reboot_after_cooldown_expired(mock_reboot):
    """Test reboot after cooldown has expired."""
    mock_db = MagicMock()
    old_reboot = datetime.now(timezone.utc) - timedelta(seconds=600)
    mock_db.get_failed_vms.return_value = [
        {
            "hostname": "vm-1",
            "status": "error",
            "healthy": None,
            "reboot_count": 1,
            "last_reboot_time": old_reboot,
        }
    ]

    service = AutoRebootService(
        database=mock_db,
        max_attempts=3,
        cooldown_seconds=300,
        terraform_dir="/tmp/terraform",
    )
    service._check_and_reboot()

    mock_reboot.assert_called_once_with("vm-1")


@patch.object(AutoRebootService, "_reboot_vm")
def test_check_and_reboot_naive_timestamp(mock_reboot):
    """Test reboot with naive (no timezone) last_reboot_time from DB."""
    mock_db = MagicMock()
    # DB may return naive timestamps - service should handle this
    naive_old_reboot = datetime.utcnow() - timedelta(seconds=600)
    mock_db.get_failed_vms.return_value = [
        {
            "hostname": "vm-1",
            "status": "error",
            "healthy": None,
            "reboot_count": 1,
            "last_reboot_time": naive_old_reboot,
        }
    ]

    service = AutoRebootService(
        database=mock_db,
        max_attempts=3,
        cooldown_seconds=300,
        terraform_dir="/tmp/terraform",
    )
    service._check_and_reboot()

    mock_reboot.assert_called_once_with("vm-1")


@patch.object(AutoRebootService, "_reboot_vm")
def test_check_and_reboot_no_failed_vms(mock_reboot):
    """Test check with no failed VMs."""
    mock_db = MagicMock()
    mock_db.get_failed_vms.return_value = []

    service = AutoRebootService(database=mock_db, terraform_dir="/tmp/terraform")
    service._check_and_reboot()

    mock_reboot.assert_not_called()


def test_start_and_stop():
    """Test that the service starts and stops cleanly."""
    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        check_interval_seconds=1,
        terraform_dir="/tmp/terraform",
    )

    service.start()
    assert service._thread is not None
    assert service._thread.is_alive()

    mock_db.ensure_reboot_columns.assert_called_once()

    service.stop()
    assert not service._thread.is_alive()
