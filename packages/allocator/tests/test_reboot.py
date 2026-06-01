"""Tests for the automated VM reboot system."""

import pytest
from unittest.mock import MagicMock, patch, ANY
from datetime import datetime, timezone, timedelta

# Mock psycopg2 before importing modules
mock_psycopg2 = MagicMock()
mock_psycopg2.IntegrityError = type("IntegrityError", (Exception,), {})

with patch.dict(
    "sys.modules",
    {
        "psycopg2": mock_psycopg2,
        "psycopg2.extensions": MagicMock(),
        "psycopg2.pool": mock_psycopg2.pool,
    },
):
    from lablink_allocator_service.database import PostgresqlDatabase
    import lablink_allocator_service.reboot as reboot_mod
    AutoRebootService = reboot_mod.AutoRebootService


@pytest.fixture
def mock_db_connection():
    """Fixture returning (mock_conn, mock_cursor, mock_pool)."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    # conn.cursor() returns the cursor directly (real psycopg2 behavior).
    mock_conn.cursor.return_value = mock_cursor

    mock_pool = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_psycopg2.pool.ThreadedConnectionPool.return_value = mock_pool

    return mock_conn, mock_cursor, mock_pool


@pytest.fixture
def db_instance(mock_db_connection):
    """Fixture returning a PostgresqlDatabase wired to a mocked pool."""
    mock_conn, mock_cursor, mock_pool = mock_db_connection
    db = PostgresqlDatabase(
        dbname="testdb",
        user="testuser",
        password="testpassword",
        host="localhost",
        port=5432,
        table_name="vms",
    )
    db.conn = mock_conn
    db.cursor = mock_cursor
    db._pool = mock_pool
    return db


# --- Database method tests ---


def test_update_vm_status_rebooting(db_instance):
    """Test that 'rebooting' is a valid VM status."""
    db_instance.update_vm_status("vm-1", "rebooting")
    db_instance.cursor.execute.assert_called_with(ANY, ("vm-1", "rebooting"))


def test_get_failed_vms(db_instance):
    """Test retrieving failed VMs."""
    db_instance.cursor.fetchall.return_value = [
        ("vm-1", "error", None, 0, None, None, None),
        (
            "vm-2",
            "running",
            "Unhealthy",
            1,
            datetime(2025, 1, 1),
            "user@test.com",
            None,
        ),
    ]

    result = db_instance.get_failed_vms()

    assert len(result) == 2
    assert result[0]["hostname"] == "vm-1"
    assert result[0]["status"] == "error"
    assert result[0]["reboot_count"] == 0
    assert result[1]["hostname"] == "vm-2"
    assert result[1]["healthy"] == "Unhealthy"
    assert result[1]["reboot_count"] == 1


def test_get_failed_vms_includes_useremail(db_instance):
    """Test that get_failed_vms returns useremail for assignment-aware reboot."""
    db_instance.cursor.fetchall.return_value = [
        ("vm-assigned", "error", None, 1, None, "student@example.com", None),
        ("vm-unassigned", "error", None, 0, None, None, None),
    ]

    result = db_instance.get_failed_vms()

    assert result[0]["useremail"] == "student@example.com"
    assert result[1]["useremail"] is None


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
        ("vm-stale", "initializing", None, 0, None, None, None),
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
        ("vm-stuck", "rebooting", None, 1, datetime(2025, 1, 1), None, None),
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


def test_get_failed_vms_includes_silent_running_vm(db_instance):
    """Running VM with stale last_seen_at is flagged for reboot."""
    stale = datetime(2025, 1, 1, tzinfo=timezone.utc)
    db_instance.cursor.fetchall.return_value = [
        ("vm-silent", "running", "Healthy", 0, None, "s@test", stale),
    ]

    result = db_instance.get_failed_vms(stale_heartbeat_minutes=3)

    assert len(result) == 1
    assert result[0]["hostname"] == "vm-silent"
    assert result[0]["last_seen_at"] == stale

    query = db_instance.cursor.execute.call_args[0][0]
    assert "last_seen_at" in query
    assert "3 minutes" in query


def test_get_failed_vms_default_stale_heartbeat_is_3_minutes(db_instance):
    """Default stale_heartbeat_minutes is 3 (6x the 30s heartbeat cadence)."""
    db_instance.cursor.fetchall.return_value = []
    db_instance.get_failed_vms()  # no explicit arguments

    query = db_instance.cursor.execute.call_args[0][0]
    assert "3 minutes" in query


def test_get_failed_vms_null_last_seen_not_flagged(db_instance):
    """Brand-new VMs with last_seen_at IS NULL must not be flagged.

    Otherwise every VM would be marked silent immediately on creation,
    before the heartbeat thread has had a chance to post.
    """
    db_instance.cursor.fetchall.return_value = []
    db_instance.get_failed_vms(stale_heartbeat_minutes=3)

    query = db_instance.cursor.execute.call_args[0][0]
    assert "last_seen_at IS NOT NULL" in query


def test_get_failed_vms_heartbeat_only_matches_running(db_instance):
    """The heartbeat staleness branch guards on status='running' so we
    don't double-count VMs already caught by the rebooting/initializing
    stale predicates."""
    db_instance.cursor.fetchall.return_value = []
    db_instance.get_failed_vms()

    query = db_instance.cursor.execute.call_args[0][0]
    # The heartbeat branch appears alongside status = 'running'
    assert "status = 'running'" in query
    assert "last_seen_at IS NOT NULL" in query


def test_record_heartbeat_updates_columns(db_instance):
    """record_heartbeat persists boot_id, disk_free_pct, and bumps last_seen_at."""
    db_instance.cursor.fetchone.return_value = (None,)
    ok = db_instance.record_heartbeat(
        hostname="vm-1",
        boot_id="abc-123",
        disk_free_pct=87,
    )
    assert ok is True

    # The UPDATE call is the second execute (first was the SELECT).
    update_call = db_instance.cursor.execute.call_args_list[-1]
    query = update_call[0][0]
    params = update_call[0][1]
    assert "last_seen_at = NOW()" in query
    assert "boot_id = %s" in query
    assert "disk_free_pct = %s" in query
    assert "crd_active" not in query
    assert params == ("abc-123", 87, "vm-1")


def test_record_heartbeat_unknown_hostname_returns_false(db_instance, caplog):
    """Heartbeat for an unknown hostname returns False and logs warning."""
    db_instance.cursor.fetchone.return_value = None

    ok = db_instance.record_heartbeat(
        hostname="vm-missing",
        boot_id="bid",
        disk_free_pct=50,
    )

    assert ok is False
    assert "unknown hostname" in caplog.text.lower()


def test_record_heartbeat_warns_on_boot_id_change(db_instance, caplog):
    """Heartbeat with a different boot_id than stored emits a warning."""
    db_instance.cursor.fetchone.return_value = ("prev-bid",)

    db_instance.record_heartbeat(
        hostname="vm-1",
        boot_id="new-bid",
        disk_free_pct=50,
    )

    assert "boot_id changed" in caplog.text


def test_record_heartbeat_warns_on_low_disk(db_instance, caplog):
    """disk_free_pct under 10 % emits a warning."""
    db_instance.cursor.fetchone.return_value = ("bid",)

    db_instance.record_heartbeat(
        hostname="vm-1",
        boot_id="bid",
        disk_free_pct=5,
    )

    assert "disk_free_pct low" in caplog.text


def test_record_heartbeat_no_warn_on_first_boot_id(db_instance, caplog):
    """First heartbeat (previous boot_id is NULL) must not warn."""
    db_instance.cursor.fetchone.return_value = (None,)

    db_instance.record_heartbeat(
        hostname="vm-1",
        boot_id="new-bid",
        disk_free_pct=50,
    )

    assert "boot_id changed" not in caplog.text


def test_touch_last_seen_only_updates_timestamp(db_instance):
    """touch_last_seen updates last_seen_at without touching other columns."""
    db_instance.touch_last_seen("vm-1")

    query = db_instance.cursor.execute.call_args[0][0]
    assert "last_seen_at = NOW()" in query
    # No other mutable columns touched.
    assert "boot_id" not in query
    assert "status" not in query


def test_touch_last_seen_swallows_errors(db_instance, caplog):
    """touch_last_seen logs and continues on DB error; never raises.

    It is called on the hot path of every client->allocator endpoint,
    so a failure here must not take the endpoint down.
    """
    db_instance.cursor.execute.side_effect = Exception("DB down")

    # No exception should propagate.
    db_instance.touch_last_seen("vm-1")

    assert "touch last_seen" in caplog.text.lower()


def test_record_reboot(db_instance):
    """Test recording a reboot attempt."""
    db_instance.record_reboot("vm-1")
    db_instance.cursor.execute.assert_called_with(ANY, ("vm-1",))

    # Verify reboot bookkeeping fields are set but the student's
    # assignment is preserved (so the student keeps their VM slot
    # across reboots).
    query = db_instance.cursor.execute.call_args[0][0]
    assert "useremail = NULL" not in query
    assert "status = 'rebooting'" in query
    assert "reboot_count" in query


def test_record_reboot_error(db_instance, caplog):
    """Test error handling in record_reboot."""
    db_instance.cursor.execute.side_effect = Exception("DB error")
    with pytest.raises(Exception, match="DB error"):
        db_instance.record_reboot("vm-1")


def test_release_assignment(db_instance):
    """Test releasing a VM's assignment when reboot attempts are exhausted."""
    db_instance.release_assignment("vm-1")
    db_instance.cursor.execute.assert_called_with(ANY, ("vm-1",))

    query = db_instance.cursor.execute.call_args[0][0]
    assert "useremail = NULL" in query
    assert "status = 'error'" in query
    # reboot_count is intentionally preserved for diagnostics
    assert "reboot_count" not in query


def test_release_assignment_error(db_instance, caplog):
    """Test error handling in release_assignment."""
    db_instance.cursor.execute.side_effect = Exception("DB error")
    with pytest.raises(Exception, match="DB error"):
        db_instance.release_assignment("vm-1")
    assert "Failed to release assignment for" in caplog.text


def test_ensure_reboot_columns(db_instance):
    """Test that ensure_reboot_columns adds columns."""
    db_instance.ensure_reboot_columns()
    assert db_instance.cursor.execute.call_count == 2
    calls = [str(c) for c in db_instance.cursor.execute.call_args_list]
    assert any("reboot_count" in c for c in calls)
    assert any("last_reboot_time" in c for c in calls)


# --- AutoRebootService tests ---


def test_ssh_cold_reboot_success(monkeypatch):
    """Test successful SSH cold reboot."""
    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        terraform_dir="/tmp/terraform",
    )

    mock_run = MagicMock()
    mock_run.return_value.returncode = 0
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._ssh_cold_reboot("1.2.3.4", "/tmp/key.pem")

    assert result is True
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "ssh" in cmd
    assert "ubuntu@1.2.3.4" in cmd
    remote_cmd = cmd[-1]
    assert "docker ps -aq" in remote_cmd
    assert "xargs -r docker rm -f" in remote_cmd
    assert "sudo cloud-init clean && sudo reboot" in remote_cmd


def test_ssh_cold_reboot_exit_255(monkeypatch):
    """Test SSH cold reboot with exit code 255 (connection reset by reboot)."""
    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        terraform_dir="/tmp/terraform",
    )

    mock_run = MagicMock()
    mock_run.return_value.returncode = 255
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._ssh_cold_reboot("1.2.3.4", "/tmp/key.pem")
    assert result is True


def test_ssh_cold_reboot_timeout(monkeypatch):
    """Test SSH cold reboot timeout."""
    import subprocess

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        terraform_dir="/tmp/terraform",
    )

    mock_run = MagicMock(side_effect=subprocess.TimeoutExpired("ssh", 30))
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._ssh_cold_reboot("1.2.3.4", "/tmp/key.pem")
    assert result is False


def test_ssh_cold_reboot_failure(monkeypatch):
    """Test SSH cold reboot with non-zero exit code."""
    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        terraform_dir="/tmp/terraform",
    )

    mock_run = MagicMock()
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Connection refused"
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._ssh_cold_reboot("1.2.3.4", "/tmp/key.pem")
    assert result is False


def test_ssh_warm_reboot_success(monkeypatch):
    """Test warm reboot sends 'sudo reboot' without cloud-init clean."""
    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        terraform_dir="/tmp/terraform",
    )

    mock_run = MagicMock()
    mock_run.return_value.returncode = 0
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._ssh_warm_reboot("1.2.3.4", "/tmp/key.pem")

    assert result is True
    cmd = mock_run.call_args[0][0]
    assert "ubuntu@1.2.3.4" in cmd
    assert cmd[-1] == "sudo reboot"


def test_ssh_warm_reboot_does_not_clean_cloud_init(monkeypatch):
    """Warm reboot must NOT run cloud-init clean (container would be destroyed)."""
    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        terraform_dir="/tmp/terraform",
    )

    mock_run = MagicMock()
    mock_run.return_value.returncode = 0
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    service._ssh_warm_reboot("1.2.3.4", "/tmp/key.pem")

    cmd = mock_run.call_args[0][0]
    full_cmd = " ".join(cmd)
    assert "cloud-init clean" not in full_cmd


def test_reboot_vm_ssh_success(monkeypatch):
    """Test successful VM reboot via SSH."""
    mock_provider = MagicMock(can_recover_hosts=True)
    mock_provider.get_host_access.return_value = ("i-12345", "1.2.3.4", "/tmp/key.pem")

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        provider=mock_provider,
    )

    mock_run = MagicMock()
    mock_run.return_value.returncode = 0
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._reboot_vm("vm-1", assigned=False)

    assert result is True
    mock_db.record_reboot.assert_called_once_with("vm-1")


def test_reboot_vm_ssh_fails_stop_start_succeeds(monkeypatch):
    """Test fallback to stop/start when SSH fails."""
    mock_provider = MagicMock(can_recover_hosts=True)
    mock_provider.get_host_access.return_value = ("i-12345", "1.2.3.4", "/tmp/key.pem")
    mock_provider.recover_hosts.return_value = True

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        provider=mock_provider,
    )

    # SSH fails with exit code 1
    mock_run = MagicMock()
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Connection refused"
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._reboot_vm("vm-1", assigned=False)

    assert result is True
    mock_db.record_reboot.assert_called_once_with("vm-1")


def test_reboot_vm_no_ip_stop_start_succeeds(monkeypatch):
    """Test stop/start fallback when no public IP available."""
    mock_provider = MagicMock(can_recover_hosts=True)
    # No public IP — SSH skipped; falls straight to recover_hosts
    mock_provider.get_host_access.return_value = ("i-12345", None, None)
    mock_provider.recover_hosts.return_value = True

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        provider=mock_provider,
    )

    result = service._reboot_vm("vm-1", assigned=False)

    assert result is True
    mock_db.record_reboot.assert_called_once_with("vm-1")


def test_reboot_vm_all_methods_fail(monkeypatch):
    """Test when SSH and stop/start both fail."""
    mock_provider = MagicMock(can_recover_hosts=True)
    mock_provider.get_host_access.return_value = ("i-12345", "1.2.3.4", "/tmp/key.pem")
    mock_provider.recover_hosts.return_value = False

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        provider=mock_provider,
    )

    # SSH fails
    mock_run = MagicMock()
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Connection refused"
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._reboot_vm("vm-1", assigned=False)

    assert result is False
    mock_db.record_reboot.assert_not_called()


def test_reboot_vm_instance_not_found(monkeypatch):
    """Test reboot when instance not found via provider."""
    mock_provider = MagicMock(can_recover_hosts=True)
    # Provider cannot find the instance
    mock_provider.get_host_access.return_value = (None, None, None)

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        provider=mock_provider,
    )

    result = service._reboot_vm("vm-nonexistent", assigned=False)

    assert result is False
    mock_db.record_reboot.assert_not_called()


def test_reboot_vm_uses_warm_reboot_for_assigned_vm(monkeypatch):
    """Assigned VMs (useremail set) get warm reboot to preserve container."""
    mock_provider = MagicMock(can_recover_hosts=True)
    mock_provider.get_host_access.return_value = ("i-12345", "1.2.3.4", "/tmp/key.pem")

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        provider=mock_provider,
    )

    mock_run = MagicMock()
    mock_run.return_value.returncode = 0
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._reboot_vm("vm-1", assigned=True)

    assert result is True
    cmd = mock_run.call_args[0][0]
    assert cmd[-1] == "sudo reboot"
    assert "cloud-init clean" not in " ".join(cmd)
    mock_db.record_reboot.assert_called_once_with("vm-1")


def test_reboot_vm_uses_cold_reboot_for_unassigned_vm(monkeypatch):
    """Unassigned VMs (no useremail) get cold reboot with cloud-init clean."""
    mock_provider = MagicMock(can_recover_hosts=True)
    mock_provider.get_host_access.return_value = ("i-12345", "1.2.3.4", "/tmp/key.pem")

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        provider=mock_provider,
    )

    mock_run = MagicMock()
    mock_run.return_value.returncode = 0
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._reboot_vm("vm-1", assigned=False)

    assert result is True
    cmd = mock_run.call_args[0][0]
    remote_cmd = cmd[-1]
    assert "docker ps -aq" in remote_cmd
    assert "xargs -r docker rm -f" in remote_cmd
    assert "sudo cloud-init clean && sudo reboot" in remote_cmd
    mock_db.record_reboot.assert_called_once_with("vm-1")


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
            "useremail": None,
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
            "useremail": None,
        }
    ]

    service = AutoRebootService(
        database=mock_db,
        max_attempts=3,
        cooldown_seconds=300,
        terraform_dir="/tmp/terraform",
    )
    service._check_and_reboot()

    mock_reboot.assert_called_once_with("vm-1", assigned=False)
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
            "useremail": None,
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
            "useremail": None,
        }
    ]

    service = AutoRebootService(
        database=mock_db,
        max_attempts=3,
        cooldown_seconds=300,
        terraform_dir="/tmp/terraform",
    )
    service._check_and_reboot()

    mock_reboot.assert_called_once_with("vm-1", assigned=False)


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
            "useremail": None,
        }
    ]

    service = AutoRebootService(
        database=mock_db,
        max_attempts=3,
        cooldown_seconds=300,
        terraform_dir="/tmp/terraform",
    )
    service._check_and_reboot()

    mock_reboot.assert_called_once_with("vm-1", assigned=False)


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
            "useremail": None,
        }
    ]

    service = AutoRebootService(
        database=mock_db,
        max_attempts=3,
        cooldown_seconds=300,
        terraform_dir="/tmp/terraform",
    )
    service._check_and_reboot()

    mock_reboot.assert_called_once_with("vm-1", assigned=False)


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


@patch.object(AutoRebootService, "_reboot_vm")
def test_check_and_reboot_passes_assigned_true_for_assigned_vm(mock_reboot):
    """Test that assigned VMs get assigned=True passed to _reboot_vm."""
    mock_db = MagicMock()
    mock_db.get_failed_vms.return_value = [
        {
            "hostname": "vm-1",
            "status": "error",
            "healthy": None,
            "reboot_count": 0,
            "last_reboot_time": None,
            "useremail": "student@example.com",
        }
    ]

    service = AutoRebootService(
        database=mock_db,
        max_attempts=3,
        cooldown_seconds=300,
        terraform_dir="/tmp/terraform",
    )
    service._check_and_reboot()

    mock_reboot.assert_called_once_with("vm-1", assigned=True)


@patch.object(AutoRebootService, "_reboot_vm")
def test_check_and_reboot_passes_assigned_false_for_unassigned_vm(mock_reboot):
    """Test that unassigned VMs get assigned=False passed to _reboot_vm."""
    mock_db = MagicMock()
    mock_db.get_failed_vms.return_value = [
        {
            "hostname": "vm-1",
            "status": "error",
            "healthy": None,
            "reboot_count": 0,
            "last_reboot_time": None,
            "useremail": None,
        }
    ]

    service = AutoRebootService(
        database=mock_db,
        max_attempts=3,
        cooldown_seconds=300,
        terraform_dir="/tmp/terraform",
    )
    service._check_and_reboot()

    mock_reboot.assert_called_once_with("vm-1", assigned=False)


def test_reboot_vm_ssh_fails_stop_start_assigned_falls_back(monkeypatch):
    """Assigned VM: SSH warm reboot fails, stop/start fallback still fires.

    Documents that stop/start is invoked regardless of assignment state.
    The "stop/start is always cold" semantic refers to post-boot behavior
    (cloud-init re-runs user_data), not to whether fallback triggers.
    """
    mock_provider = MagicMock(can_recover_hosts=True)
    mock_provider.get_host_access.return_value = ("i-12345", "1.2.3.4", "/tmp/key.pem")
    mock_provider.recover_hosts.return_value = True

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        provider=mock_provider,
    )

    # SSH fails with a non-zero, non-255 exit code
    mock_run = MagicMock()
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Connection refused"
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._reboot_vm("vm-1", assigned=True)

    assert result is True
    # SSH attempt was the warm path (sudo reboot, no cloud-init clean)
    cmd = mock_run.call_args[0][0]
    assert cmd[-1] == "sudo reboot"
    # Stop/start was invoked as fallback via provider
    mock_provider.recover_hosts.assert_called_once()
    (handles,), _ = mock_provider.recover_hosts.call_args
    assert handles[0].id == "i-12345"
    mock_db.record_reboot.assert_called_once_with("vm-1")


def test_reboot_vm_no_ip_assigned_falls_back_to_stop_start(monkeypatch):
    """Assigned VM with no public IP skips SSH and goes straight to stop/start."""
    mock_provider = MagicMock(can_recover_hosts=True)
    # No IP or key — SSH skipped; falls straight to recover_hosts
    mock_provider.get_host_access.return_value = ("i-12345", None, None)
    mock_provider.recover_hosts.return_value = True

    # Guard: subprocess.run must NOT be called (no SSH attempt without IP)
    mock_run = MagicMock()
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        provider=mock_provider,
    )

    result = service._reboot_vm("vm-1", assigned=True)

    assert result is True
    mock_run.assert_not_called()
    mock_provider.recover_hosts.assert_called_once()
    (handles,), _ = mock_provider.recover_hosts.call_args
    assert handles[0].id == "i-12345"
    mock_db.record_reboot.assert_called_once_with("vm-1")


def test_reboot_vm_all_methods_fail_assigned(monkeypatch):
    """Assigned VM: when SSH and stop/start both fail, no reboot recorded."""
    mock_provider = MagicMock(can_recover_hosts=True)
    mock_provider.get_host_access.return_value = ("i-12345", "1.2.3.4", "/tmp/key.pem")
    mock_provider.recover_hosts.return_value = False

    mock_db = MagicMock()
    service = AutoRebootService(
        database=mock_db,
        region="us-west-2",
        provider=mock_provider,
    )

    mock_run = MagicMock()
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Connection refused"
    monkeypatch.setattr(reboot_mod.subprocess, "run", mock_run)

    result = service._reboot_vm("vm-1", assigned=True)

    assert result is False
    mock_provider.recover_hosts.assert_called_once()
    (handles,), _ = mock_provider.recover_hosts.call_args
    assert handles[0].id == "i-12345"
    mock_db.record_reboot.assert_not_called()


# --- Provider seam tests ---


def test_reboot_vm_uses_provider_recover_when_capable(monkeypatch):
    """When provider.can_recover_hosts is True, recover_hosts is called instead of stop_start."""
    prov = MagicMock(can_recover_hosts=True)
    # Return None for IP so SSH is skipped and we reach the EC2-fallback branch
    prov.get_host_access.return_value = ("i-42", None, None)
    prov.recover_hosts.return_value = True
    svc = reboot_mod.AutoRebootService(
        database=MagicMock(),
        region="us-west-2",
        provider=prov,
    )

    assert svc._reboot_vm("vm-1", assigned=False) is True
    prov.recover_hosts.assert_called_once()
    (handles,), _ = prov.recover_hosts.call_args
    assert handles[0].id == "i-42"
    assert handles[0].provider_metadata["region"] == "us-west-2"
    svc.database.record_reboot.assert_called_once_with("vm-1")

    prov.recover_hosts.return_value = False
    prov.recover_hosts.reset_mock()
    svc.database.record_reboot.reset_mock()
    assert svc._reboot_vm("vm-1", assigned=False) is False
    svc.database.record_reboot.assert_not_called()


def test_reboot_vm_skips_ec2_when_provider_cannot_recover():
    """When provider.can_recover_hosts is False, no recovery is attempted."""
    svc = reboot_mod.AutoRebootService(
        database=MagicMock(),
        region="us-west-2",
        provider=MagicMock(can_recover_hosts=False),
    )

    result = svc._reboot_vm("vm-9", assigned=False)
    assert result is False
    # get_host_access must NOT have been called (capability gate blocks all lookups)
    svc.provider.get_host_access.assert_not_called()
    svc.database.record_reboot.assert_not_called()


def test_reboot_vm_skips_all_aws_calls_when_provider_cannot_recover():
    """Manual/BYO providers must not invoke ANY AWS EC2 calls in _reboot_vm.

    Reproduces the manual-deployment NoCredentialsError loop where the
    upstream lookup (`get_instance_id_by_name`) fires before the
    capability check on the stop/start fallback. With no credentials in
    the container, botocore raises NoCredentialsError and the reboot
    thread spams the log every check interval.

    After the provider-seam refactor, all AWS lookups live inside
    AWSProvider.get_host_access — the capability gate returns False before
    ever reaching that call, so no botocore call is made.
    """
    svc = reboot_mod.AutoRebootService(
        database=MagicMock(),
        region="us-west-2",
        provider=MagicMock(can_recover_hosts=False, name="manual"),
    )

    result = svc._reboot_vm("LAPTOP-M8NLMMGL", assigned=False)

    assert result is False
    # Capability gate must fire before get_host_access or recover_hosts
    svc.provider.get_host_access.assert_not_called()
    svc.provider.recover_hosts.assert_not_called()
    svc.database.record_reboot.assert_not_called()
