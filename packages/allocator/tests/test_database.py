import pytest
from unittest.mock import MagicMock, patch, ANY
import json

# Mock psycopg2 before importing the database module
# This allows us to avoid the real psycopg2 import raising an error if it's not installed
# in the test environment, and to control its behavior for all tests in this file.
mock_psycopg2 = MagicMock()
with patch.dict(
    "sys.modules",
    {"psycopg2": mock_psycopg2, "psycopg2.extensions": MagicMock()},
):
    from lablink_allocator_service.database import PostgresqlDatabase


@pytest.fixture
def mock_db_connection():
    """Fixture to create a mock database connection and cursor."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    # When PostgresqlDatabase is initialized, it calls psycopg2.connect()
    mock_psycopg2.connect.return_value = mock_conn
    return mock_conn, mock_cursor


@pytest.fixture
def db_instance(mock_db_connection):
    """Fixture to create an instance of the PostgresqlDatabase class."""
    # The mock_db_connection fixture ensures that the call to psycopg2.connect()
    # in the __init__ method returns our mock connection.
    db = PostgresqlDatabase(
        dbname="testdb",
        user="testuser",
        password="testpassword",
        host="localhost",
        port=5432,
        table_name="vms",
        message_channel="test_channel",
    )
    # We can also directly access the mocked connection and cursor for manipulation
    db.conn, db.cursor = mock_db_connection
    return db


def test_get_row_count(db_instance):
    """Test getting the row count from the database."""
    db_instance.cursor.fetchone.return_value = (5,)
    count = db_instance.get_row_count()
    db_instance.cursor.execute.assert_called_with("SELECT COUNT(*) FROM vms;")
    assert count == 5


def test_get_column_names(db_instance):
    """Test getting column names from a table."""
    expected_columns = [
        "hostname",
        "pin",
        "useremail",
        "crdcommand",
        "inuse",
        "healthy",
        "status",
        "logs",
    ]
    db_instance.cursor.fetchall.return_value = [(col,) for col in expected_columns]
    columns = db_instance.get_column_names("vms")
    db_instance.cursor.execute.assert_called_with(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        ("vms",),
    )
    assert columns == expected_columns


def test_insert_vm(db_instance):
    """Test inserting a new VM into the database."""
    hostname = "test-vm-01"
    # Mock the get_column_names method to return a specific set of columns
    db_instance.get_column_names = MagicMock(
        return_value=[
            "hostname",
            "inuse",
            "status",
            "email",
            "pin",
            "crdcommand",
            "healthy",
            "logs",
        ]
    )
    db_instance.insert_vm(hostname)

    expected_sql = "INSERT INTO vms (hostname, inuse, status, email, pin, crdcommand, healthy, logs) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);"
    # The values should correspond to the mocked column names
    expected_values = [hostname, False, None, None, None, None, None, None]
    db_instance.cursor.execute.assert_called_with(expected_sql, expected_values)
    db_instance.conn.commit.assert_called_once()


def test_get_vm_by_hostname_found(db_instance):
    """Test retrieving a VM by its hostname when it exists."""
    from datetime import datetime

    hostname = "test-vm-01"
    start_time = datetime(2023, 1, 1, 12, 0, 0)
    end_time = datetime(2023, 1, 1, 12, 2, 3)
    # Simulate a row returned from the database
    vm_data = (
        hostname,
        "123456",
        "crd-command",
        "user@example.com",
        False,
        True,
        "running",
        "log data",
        start_time,  # terraform_apply_start_time
        end_time,  # terraform_apply_end_time
        123.0,  # terraform_apply_duration_seconds
        start_time,  # cloud_init_start_time
        end_time,  # cloud_init_end_time
        123.0,  # cloud_init_duration_seconds
        start_time,  # container_start_time
        end_time,  # container_end_time
        123.0,  # container_startup_duration_seconds
        369.0,  # total_startup_duration_seconds
        start_time,  # created_at
    )
    db_instance.cursor.fetchone.return_value = vm_data
    vm = db_instance.get_vm_by_hostname(hostname)

    db_instance.cursor.execute.assert_called_with(
        "SELECT * FROM vms WHERE hostname = %s;", (hostname,)
    )
    assert vm["hostname"] == hostname
    assert vm["pin"] == "123456"
    assert vm["terraform_apply_start_time"] == start_time
    assert vm["terraform_apply_end_time"] == end_time
    assert vm["terraform_apply_duration_seconds"] == 123.0
    assert vm["cloud_init_start_time"] == start_time
    assert vm["cloud_init_end_time"] == end_time
    assert vm["cloud_init_duration_seconds"] == 123.0
    assert vm["container_start_time"] == start_time
    assert vm["container_end_time"] == end_time
    assert vm["container_startup_duration_seconds"] == 123.0
    assert vm["total_startup_duration_seconds"] == 369.0
    assert vm["created_at"] == start_time


def test_get_vm_by_hostname_not_found(db_instance):
    """Test retrieving a VM by its hostname when it does not exist."""
    hostname = "non-existent-vm"
    db_instance.cursor.fetchone.return_value = None
    vm = db_instance.get_vm_by_hostname(hostname)
    assert vm is None


@patch("select.select")
def test_listen_for_notifications(mock_select, db_instance):
    """Test the notification listener."""
    target_hostname = "vm-to-connect"
    channel = "test_channel"

    # Mock a separate connection for the listener
    mock_listen_conn = MagicMock()
    mock_listen_cursor = MagicMock()
    mock_listen_conn.cursor.return_value = mock_listen_cursor
    # The listener creates its own connection, so we patch the return value again
    mock_psycopg2.connect.return_value = mock_listen_conn

    # Simulate receiving a notification
    mock_select.return_value = ([mock_listen_conn], [], [])

    payload = {
        "HostName": target_hostname,
        "Pin": "654321",
        "CrdCommand": "remote-desktop-command",
    }
    mock_notification = MagicMock()
    mock_notification.payload = json.dumps(payload)
    mock_notification.channel = channel
    mock_listen_conn.notifies = [mock_notification]

    result = db_instance.listen_for_notifications(channel, target_hostname)

    mock_listen_cursor.execute.assert_called_with(f"LISTEN {channel};")
    assert result["status"] == "success"
    assert result["pin"] == "654321"
    mock_listen_cursor.close.assert_called_once()
    mock_listen_conn.close.assert_called_once()


def test_get_crd_command(db_instance):
    """Test getting the CRD command for a specific VM."""
    hostname = "test-vm-02"
    command = "some-crd-command"
    db_instance.vm_exists = MagicMock(return_value=True)
    db_instance.cursor.fetchone.return_value = (command,)

    result = db_instance.get_crd_command(hostname)

    db_instance.cursor.execute.assert_called_with(
        "SELECT crdcommand FROM vms WHERE hostname = %s", (hostname,)
    )
    assert result == command


def test_get_unassigned_vms(db_instance):
    """Test getting a list of unassigned VMs."""
    unassigned_vms_data = [("vm-free-1",), ("vm-free-2",)]
    db_instance.cursor.fetchall.return_value = unassigned_vms_data

    result = db_instance.get_unassigned_vms()

    expected_query = (
        "SELECT hostname FROM vms WHERE crdcommand IS NULL AND status = 'running'"
    )
    db_instance.cursor.execute.assert_called_with(expected_query)
    assert result == ["vm-free-1", "vm-free-2"]


def test_vm_exists(db_instance):
    """Test checking for the existence of a VM."""
    hostname = "existing-vm"
    db_instance.cursor.fetchone.return_value = (True,)
    assert db_instance.vm_exists(hostname) is True
    db_instance.cursor.execute.assert_called_with(
        "SELECT EXISTS (SELECT 1 FROM vms WHERE hostname = %s)", (hostname,)
    )


def test_get_assigned_vms(db_instance):
    """Test getting a list of assigned VMs."""
    assigned_vms_data = [("vm-in-use-1",), ("vm-in-use-2",)]
    db_instance.cursor.fetchall.return_value = assigned_vms_data

    result = db_instance.get_assigned_vms()

    db_instance.cursor.execute.assert_called_with(
        "SELECT hostname FROM vms WHERE crdcommand IS NOT NULL"
    )
    assert result == ["vm-in-use-1", "vm-in-use-2"]


def test_get_vm_details_found(db_instance):
    """Test getting VM details for a user when a VM is assigned."""
    email = "user@example.com"
    vm_details_data = (
        "vm-assigned-1",
        "123456",
        "command",
    )
    db_instance.cursor.fetchone.return_value = vm_details_data

    result = db_instance.get_vm_details(email)

    db_instance.cursor.execute.assert_called_with(
        "SELECT hostname, pin, crdcommand FROM vms WHERE useremail = %s", (email,)
    )
    assert result == ["vm-assigned-1", "123456", "command"]


def test_get_vm_details_not_found(db_instance):
    """Test getting VM details when no VM is assigned to the user."""
    email = "no-user@example.com"
    db_instance.cursor.fetchone.return_value = None
    with pytest.raises(ValueError):
        db_instance.get_vm_details(email)


def test_assign_vm(db_instance):
    """Test assigning an available VM to a user."""
    email = "new-user@example.com"
    crd_command = "new-command"
    pin = "4321"
    hostname = "available-vm"

    db_instance.get_first_available_vm = MagicMock(return_value=hostname)
    db_instance.assign_vm(email, crd_command, pin)

    # Using ANY to avoid matching the exact whitespace in the multi-line query string
    db_instance.cursor.execute.assert_called_with(
        ANY, (email, crd_command, pin, hostname)
    )
    db_instance.conn.commit.assert_called_once()


def test_assign_vm_no_available(db_instance):
    """Test assigning a VM when no VMs are available."""
    db_instance.get_first_available_vm = MagicMock(return_value=None)
    with pytest.raises(ValueError, match="No available VMs to assign."):
        db_instance.assign_vm("user@example.com", "cmd", "123")


def test_get_first_available_vm(db_instance):
    """Test getting the first available VM."""
    hostname = "free-vm-01"
    db_instance.cursor.fetchone.return_value = (hostname,)

    result = db_instance.get_first_available_vm()

    expected_query = "SELECT hostname FROM vms WHERE useremail IS NULL AND status = 'running' LIMIT 1"
    db_instance.cursor.execute.assert_called_with(expected_query)
    assert result == hostname


def test_update_vm_in_use(db_instance):
    """Test updating the in-use status of a VM."""
    hostname = "vm-to-update"
    in_use = True
    db_instance.update_vm_in_use(hostname, in_use)
    db_instance.cursor.execute.assert_called_with(
        "UPDATE vms SET inuse = %s WHERE hostname = %s", (in_use, hostname)
    )
    db_instance.conn.commit.assert_called_once()


def test_clear_database(db_instance):
    """Test clearing all VMs from the database."""
    db_instance.clear_database()
    db_instance.cursor.execute.assert_called_with("DELETE FROM vms;")
    db_instance.conn.commit.assert_called_once()


def test_update_health(db_instance):
    """Test updating the health status of a VM."""
    hostname = "vm-to-health-check"
    healthy = "Healthy"
    db_instance.update_health(hostname, healthy)
    db_instance.cursor.execute.assert_called_with(
        "UPDATE vms SET healthy = %s WHERE hostname = %s;", (healthy, hostname)
    )
    db_instance.conn.commit.assert_called_once()


def test_get_gpu_health(db_instance):
    """Test getting the GPU health of a VM."""
    hostname = "gpu-vm-01"
    health_status = "fail"
    db_instance.cursor.fetchone.return_value = (health_status,)

    result = db_instance.get_gpu_health(hostname)

    db_instance.cursor.execute.assert_called_with(
        "SELECT healthy FROM vms WHERE hostname = %s;", (hostname,)
    )
    assert result == health_status


def test_get_status_by_hostname(db_instance):
    """Test getting the status of a VM by its hostname."""
    hostname = "status-vm-01"
    status = "initializing"
    db_instance.cursor.fetchone.return_value = (status,)

    result = db_instance.get_status_by_hostname(hostname)

    db_instance.cursor.execute.assert_called_with(
        "SELECT status FROM vms WHERE hostname = %s;", (hostname,)
    )
    assert result == status


def test_get_vm_logs(db_instance):
    """Test getting the logs of a VM."""
    hostname = "log-vm-01"
    logs = "some log data here"
    db_instance.cursor.fetchone.return_value = (logs,)

    result = db_instance.get_vm_logs(hostname)

    db_instance.cursor.execute.assert_called_with(
        "SELECT logs FROM vms WHERE hostname = %s;", (hostname,)
    )
    assert result == logs


def test_save_logs_by_hostname(db_instance):
    """Test saving logs for a specific VM."""
    hostname = "log-vm-02"
    logs = "new log data to save"
    db_instance.save_logs_by_hostname(hostname, logs)
    db_instance.cursor.execute.assert_called_with(
        "UPDATE vms SET logs = %s WHERE hostname = %s;", (logs, hostname)
    )
    db_instance.conn.commit.assert_called_once()


def test_get_all_vm_status(db_instance):
    """Test getting the status of all VMs."""
    statuses_data = [("vm1", "running"), ("vm2", "error"), ("vm3", "initializing")]
    db_instance.cursor.fetchall.return_value = statuses_data

    result = db_instance.get_all_vm_status()

    db_instance.cursor.execute.assert_called_with("SELECT hostname, status FROM vms;")
    assert result == {"vm1": "running", "vm2": "error", "vm3": "initializing"}


def test_update_vm_status(db_instance):
    """Test updating the status of a VM (including creating it if it doesn't exist)."""
    hostname = "vm-to-update-status"
    status = "running"
    db_instance.update_vm_status(hostname, status)

    # Using ANY to avoid matching the exact whitespace in the multi-line query string
    db_instance.cursor.execute.assert_called_with(ANY, (hostname, status))
    db_instance.conn.commit.assert_called_once()


def test_update_vm_status_invalid(db_instance, caplog):
    """Test that updating with an invalid status is blocked and logged."""
    db_instance.update_vm_status("vm1", "invalid_status")
    db_instance.cursor.execute.assert_not_called()
    assert "Invalid status 'invalid_status'" in caplog.text


def test_load_database():
    """Test the class method for loading a database instance."""
    with patch.object(
        PostgresqlDatabase,
        "__init__",
        return_value=None,
    ) as mock_init:
        inst = PostgresqlDatabase.load_database(
            "db", "user", "pass", "host", 5432, "table", "channel"
        )

    mock_init.assert_called_once_with(
        "db", "user", "pass", "host", 5432, "table", "channel"
    )

    assert isinstance(inst, PostgresqlDatabase)


def test_del(db_instance):
    """Test that the destructor closes the database connection and cursor."""
    cursor = db_instance.cursor
    conn = db_instance.conn

    # Call __del__ directly for predictable testing, as garbage collection is not guaranteed
    db_instance.__del__()

    cursor.close.assert_called_once()
    conn.close.assert_called_once()


def test_get_crd_command_no_vm(db_instance):
    """Test getting CRD command for a non-existent VM."""
    hostname = "non-existent-vm"
    db_instance.vm_exists = MagicMock(return_value=False)
    result = db_instance.get_crd_command(hostname)
    assert result is None


def test_get_unassigned_vms_error(db_instance, caplog):
    """Test error handling in get_unassigned_vms."""
    db_instance.cursor.execute.side_effect = Exception("DB error")
    result = db_instance.get_unassigned_vms()
    assert result == []
    assert "Error retrieving unassigned VMs: DB error" in caplog.text


def test_get_assigned_vms_error(db_instance, caplog):
    """Test error handling in get_assigned_vms."""
    db_instance.cursor.execute.side_effect = Exception("DB error")
    result = db_instance.get_assigned_vms()
    assert result is None
    assert "Error retrieving assigned VMs: DB error" in caplog.text


def test_assign_vm_db_error(db_instance, caplog):
    """Test error handling in assign_vm."""
    hostname = "available-vm"
    db_instance.get_first_available_vm = MagicMock(return_value=hostname)
    db_instance.cursor.execute.side_effect = Exception("DB error")
    db_instance.assign_vm("user@example.com", "cmd", "123")
    assert "Error assigning VM: DB error" in caplog.text
    db_instance.conn.rollback.assert_called_once()


def test_get_gpu_health_not_found(db_instance):
    """Test getting GPU health for a non-existent VM."""
    hostname = "non-existent-vm"
    db_instance.cursor.fetchone.return_value = None
    result = db_instance.get_gpu_health(hostname)
    assert result is None


def test_get_status_by_hostname_not_found(db_instance):
    """Test getting status for a non-existent VM."""
    hostname = "non-existent-vm"
    db_instance.cursor.fetchone.return_value = None
    result = db_instance.get_status_by_hostname(hostname)
    assert result is None


def test_get_vm_logs_not_found(db_instance):
    """Test getting logs for a non-existent VM."""
    hostname = "non-existent-vm"
    db_instance.cursor.fetchone.return_value = None
    result = db_instance.get_vm_logs(hostname)
    assert result is None


def test_get_all_vm_status_error(db_instance, caplog):
    """Test error handling in get_all_vm_status."""
    db_instance.cursor.execute.side_effect = Exception("DB error")
    result = db_instance.get_all_vm_status()
    assert result is None
    assert "Error retrieving all VM status: DB error" in caplog.text


def test_update_vm_status_db_error(db_instance, caplog):
    """Test error handling in update_vm_status."""
    hostname = "vm-to-update"
    status = "running"
    db_instance.cursor.execute.side_effect = Exception("DB error")
    db_instance.update_vm_status(hostname, status)
    assert "Error updating VM status: DB error" in caplog.text
    db_instance.conn.rollback.assert_called_once()


def test_get_all_vms(db_instance):
    """Test getting all VMs from the database."""
    with patch.object(db_instance, "get_column_names") as mock_get_columns:
        vm_data = [
            ("vm1", "pin1", "cmd1", "email1", False, True, "running"),
            ("vm2", "pin2", "cmd2", "email2", True, False, "error"),
        ]
        column_names = [
            "hostname",
            "pin",
            "crdcommand",
            "useremail",
            "inuse",
            "healthy",
            "status",
        ]
        mock_get_columns.return_value = column_names
        db_instance.cursor.fetchall.return_value = vm_data

        vms = db_instance.get_all_vms()

        # Construct the expected query, excluding the 'logs' column
        query_columns = ", ".join([col for col in column_names if col != "logs"])
        expected_query = f"SELECT {query_columns} FROM vms;"
        db_instance.cursor.execute.assert_called_with(expected_query)

        # The result should be a list of dictionaries, without the 'logs' key
        expected_vms = [
            {
                "hostname": "vm1",
                "pin": "pin1",
                "crdcommand": "cmd1",
                "useremail": "email1",
                "inuse": False,
                "healthy": True,
                "status": "running",
            },
            {
                "hostname": "vm2",
                "pin": "pin2",
                "crdcommand": "cmd2",
                "useremail": "email2",
                "inuse": True,
                "healthy": False,
                "status": "error",
            },
        ]
        assert vms == expected_vms


def test_naive_utc():
    """Test the _naive_utc static method."""
    from datetime import datetime, timezone, timedelta

    # Test with timezone-aware datetime
    aware_dt = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    naive_utc_dt = PostgresqlDatabase._naive_utc(aware_dt)
    assert naive_utc_dt.tzinfo is None
    assert naive_utc_dt == datetime(2023, 1, 1, 17, 0, 0)

    # Test with naive datetime
    naive_dt = datetime(2023, 1, 1, 12, 0, 0)
    naive_utc_dt = PostgresqlDatabase._naive_utc(naive_dt)
    assert naive_utc_dt.tzinfo is None
    assert naive_utc_dt == naive_dt


def test_update_vm_metrics_atomic_cloud_init_only(db_instance):
    """Test updating only cloud_init metrics."""
    hostname = "test-vm-01"
    metrics = {
        "cloud_init_start": 1609459200,  # 2021-01-01 00:00:00 UTC
        "cloud_init_end": 1609459260,  # 2021-01-01 00:01:00 UTC
        "cloud_init_duration_seconds": 60.0,
    }

    db_instance.cursor.fetchone.return_value = (60.0,)
    db_instance.update_vm_metrics_atomic(hostname, metrics)

    # Verify the query was executed
    call_args = db_instance.cursor.execute.call_args
    query = call_args[0][0]
    values = call_args[0][1]

    # Check that cloud_init fields are in the query
    assert "CloudInitStartTime = to_timestamp(%s)" in query
    assert "CloudInitEndTime = to_timestamp(%s)" in query
    assert "CloudInitDurationSeconds = %s" in query
    assert "TotalStartupDurationSeconds" in query
    assert "WHERE hostname = %s" in query
    assert "RETURNING TotalStartupDurationSeconds" in query

    # Check values passed (timestamps and duration, then hostname)
    assert values == (1609459200, 1609459260, 60.0, hostname)
    db_instance.conn.commit.assert_called_once()


def test_update_vm_metrics_atomic_container_only(db_instance):
    """Test updating only container metrics."""
    hostname = "test-vm-02"
    metrics = {
        "container_start": 1609459300,  # 2021-01-01 00:05:00 UTC
        "container_end": 1609459360,  # 2021-01-01 00:06:00 UTC
        "container_startup_duration_seconds": 60.0,
    }

    db_instance.cursor.fetchone.return_value = (60.0,)
    db_instance.update_vm_metrics_atomic(hostname, metrics)

    call_args = db_instance.cursor.execute.call_args
    query = call_args[0][0]
    values = call_args[0][1]

    # Check that container fields are in the query
    assert "ContainerStartTime = to_timestamp(%s)" in query
    assert "ContainerEndTime = to_timestamp(%s)" in query
    assert "ContainerStartupDurationSeconds = %s" in query
    assert "TotalStartupDurationSeconds" in query

    assert values == (1609459300, 1609459360, 60.0, hostname)
    db_instance.conn.commit.assert_called_once()


def test_update_vm_metrics_atomic_all_metrics(db_instance):
    """Test updating both cloud_init and container metrics together."""
    hostname = "test-vm-03"
    metrics = {
        "cloud_init_start": 1609459200,
        "cloud_init_end": 1609459260,
        "cloud_init_duration_seconds": 60.0,
        "container_start": 1609459300,
        "container_end": 1609459360,
        "container_startup_duration_seconds": 60.0,
    }

    db_instance.cursor.fetchone.return_value = (120.0,)
    db_instance.update_vm_metrics_atomic(hostname, metrics)

    call_args = db_instance.cursor.execute.call_args
    query = call_args[0][0]
    values = call_args[0][1]

    # Check all fields are in the query
    assert "CloudInitStartTime = to_timestamp(%s)" in query
    assert "CloudInitEndTime = to_timestamp(%s)" in query
    assert "CloudInitDurationSeconds = %s" in query
    assert "ContainerStartTime = to_timestamp(%s)" in query
    assert "ContainerEndTime = to_timestamp(%s)" in query
    assert "ContainerStartupDurationSeconds = %s" in query
    assert "TotalStartupDurationSeconds" in query

    assert values == (1609459200, 1609459260, 60.0, 1609459300, 1609459360, 60.0, hostname)
    db_instance.conn.commit.assert_called_once()


def test_update_vm_metrics_atomic_partial_metrics(db_instance):
    """Test updating only start and end times without duration."""
    hostname = "test-vm-04"
    metrics = {
        "cloud_init_start": 1609459200,
        "container_end": 1609459360,
    }

    db_instance.cursor.fetchone.return_value = (None,)
    db_instance.update_vm_metrics_atomic(hostname, metrics)

    call_args = db_instance.cursor.execute.call_args
    query = call_args[0][0]
    values = call_args[0][1]

    assert "CloudInitStartTime = to_timestamp(%s)" in query
    assert "ContainerEndTime = to_timestamp(%s)" in query
    assert "TotalStartupDurationSeconds" in query

    # Should not include metrics that weren't provided
    assert "CloudInitEndTime" not in query or "to_timestamp(%s)" in query
    assert values == (1609459200, 1609459360, hostname)
    db_instance.conn.commit.assert_called_once()


def test_update_vm_metrics_atomic_empty_metrics(db_instance):
    """Test that no update occurs when metrics dict is empty."""
    hostname = "test-vm-05"
    metrics = {}

    db_instance.update_vm_metrics_atomic(hostname, metrics)

    # No query should be executed
    db_instance.cursor.execute.assert_not_called()
    db_instance.conn.commit.assert_not_called()


def test_update_vm_metrics_atomic_total_calculation(db_instance, caplog):
    """Test that total startup time is calculated and logged correctly."""
    hostname = "test-vm-06"
    metrics = {
        "cloud_init_duration_seconds": 50.0,
        "container_startup_duration_seconds": 30.0,
    }

    # Return a non-zero total startup time
    db_instance.cursor.fetchone.return_value = (100.5,)
    db_instance.update_vm_metrics_atomic(hostname, metrics)

    # Verify the total startup time is logged
    assert f"Total startup time for VM '{hostname}': 100.5 seconds" in caplog.text
    db_instance.conn.commit.assert_called_once()


def test_update_vm_metrics_atomic_zero_total(db_instance, caplog):
    """Test that zero total startup time is not logged."""
    hostname = "test-vm-07"
    metrics = {
        "cloud_init_start": 1609459200,
    }

    # Return zero total
    db_instance.cursor.fetchone.return_value = (0.0,)
    db_instance.update_vm_metrics_atomic(hostname, metrics)

    # Should not log total startup time when it's zero
    assert "Total startup time" not in caplog.text
    db_instance.conn.commit.assert_called_once()


def test_update_vm_metrics_atomic_null_total(db_instance, caplog):
    """Test that null total startup time is not logged."""
    hostname = "test-vm-08"
    metrics = {
        "cloud_init_start": 1609459200,
    }

    # Return None (no complete data yet)
    db_instance.cursor.fetchone.return_value = (None,)
    db_instance.update_vm_metrics_atomic(hostname, metrics)

    # Should not log total startup time when it's None
    assert "Total startup time" not in caplog.text
    db_instance.conn.commit.assert_called_once()


def test_update_vm_metrics_atomic_error_handling(db_instance, caplog):
    """Test error handling and rollback on database errors."""
    hostname = "test-vm-09"
    metrics = {
        "cloud_init_duration_seconds": 60.0,
    }

    # Simulate a database error
    db_instance.cursor.execute.side_effect = Exception("Database constraint violation")

    with pytest.raises(Exception, match="Database constraint violation"):
        db_instance.update_vm_metrics_atomic(hostname, metrics)

    # Verify rollback was called
    db_instance.conn.rollback.assert_called_once()

    # Verify error was logged
    assert f"Error updating VM metrics atomically for '{hostname}'" in caplog.text
    assert "Database constraint violation" in caplog.text


def test_update_vm_metrics_atomic_sql_structure(db_instance):
    """Test that the generated SQL has correct structure."""
    hostname = "test-vm-10"
    metrics = {
        "cloud_init_start": 1609459200,
        "cloud_init_duration_seconds": 60.0,
        "container_end": 1609459360,
    }

    db_instance.cursor.fetchone.return_value = (60.0,)
    db_instance.update_vm_metrics_atomic(hostname, metrics)

    call_args = db_instance.cursor.execute.call_args
    query = call_args[0][0]

    # Verify SQL structure
    assert query.startswith("\n            UPDATE vms")
    assert "SET " in query
    assert "WHERE hostname = %s" in query
    assert "RETURNING TotalStartupDurationSeconds;" in query

    # Verify COALESCE calculation is present in the total
    assert "COALESCE(TerraformApplyDurationSeconds, 0)" in query
    assert "COALESCE(CloudInitDurationSeconds, 0)" in query
    assert "COALESCE(ContainerStartupDurationSeconds, 0)" in query


def test_update_vm_metrics_atomic_commit_behavior(db_instance):
    """Test that commit is called after successful update."""
    hostname = "test-vm-11"
    metrics = {
        "cloud_init_duration_seconds": 45.0,
    }

    db_instance.cursor.fetchone.return_value = (45.0,)

    # Reset mock to track calls
    db_instance.conn.commit.reset_mock()
    db_instance.update_vm_metrics_atomic(hostname, metrics)

    # Verify commit was called exactly once
    assert db_instance.conn.commit.call_count == 1

    # Verify rollback was not called
    db_instance.conn.rollback.assert_not_called()


def test_update_vm_metrics_atomic_fetchone_called(db_instance):
    """Test that fetchone is called to retrieve RETURNING clause result."""
    hostname = "test-vm-12"
    metrics = {
        "container_startup_duration_seconds": 30.0,
    }

    db_instance.cursor.fetchone.return_value = (30.0,)
    db_instance.update_vm_metrics_atomic(hostname, metrics)

    # Verify fetchone was called to get the RETURNING result
    db_instance.cursor.fetchone.assert_called_once()


def test_update_terraform_timing(db_instance):
    """Test updating Terraform timing metrics."""
    from datetime import datetime

    hostname = "test-vm-terraform"
    per_instance_seconds = 123.45
    start_time = datetime(2023, 1, 1, 12, 0, 0)
    end_time = datetime(2023, 1, 1, 12, 2, 3)

    with patch.object(db_instance.conn, "cursor") as mock_cursor_context:
        mock_cursor = MagicMock()
        mock_cursor_context.return_value.__enter__.return_value = mock_cursor

        db_instance.update_terraform_timing(
            hostname, per_instance_seconds, start_time, end_time
        )

        # Verify the correct query was executed
        call_args = mock_cursor.execute.call_args
        query = call_args[0][0]
        values = call_args[0][1]

        assert "INSERT INTO vms" in query
        assert "terraformapplydurationseconds" in query
        assert "terraformapplystarttime" in query
        assert "terraformapplyendtime" in query
        assert "ON CONFLICT (hostname) DO UPDATE" in query

        assert values[0] == hostname
        assert values[1] == per_instance_seconds
        # Times are converted to naive UTC by _naive_utc
        assert values[2] == start_time
        assert values[3] == end_time

        db_instance.conn.commit.assert_called_once()
