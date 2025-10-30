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
    hostname = "test-vm-01"
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
    )
    db_instance.cursor.fetchone.return_value = vm_data
    vm = db_instance.get_vm_by_hostname(hostname)

    db_instance.cursor.execute.assert_called_with(
        "SELECT * FROM vms WHERE hostname = %s;", (hostname,)
    )
    assert vm["hostname"] == hostname
    assert vm["pin"] == "123456"


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
        email,
        True,
        True,
        "running",
        "sample-logs",
    )
    db_instance.cursor.fetchone.return_value = vm_details_data

    result = db_instance.get_vm_details(email)

    db_instance.cursor.execute.assert_called_with(
        "SELECT * FROM vms WHERE useremail = %s", (email,)
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
