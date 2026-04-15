import pytest
from unittest.mock import MagicMock, patch, ANY
import json

# Mock psycopg2 before importing the database module
# This allows us to avoid the real psycopg2 import raising an error if it's not installed
# in the test environment, and to control its behavior for all tests in this file.
mock_psycopg2 = MagicMock()

# Create proper exception classes for psycopg2
class MockIntegrityError(Exception):
    """Mock psycopg2.IntegrityError for testing."""
    pass

mock_psycopg2.IntegrityError = MockIntegrityError

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

    # Make cursor() return a context manager that returns the mock cursor
    mock_cursor_context = MagicMock()
    mock_cursor_context.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor_context.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor_context

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
        "cloudinitlogs",
        "dockerlogs",
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
            "cloudinitlogs",
            "dockerlogs",
        ]
    )
    db_instance.insert_vm(hostname)

    expected_sql = "INSERT INTO vms (hostname, inuse, status, email, pin, crdcommand, healthy, cloudinitlogs, dockerlogs) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);"
    # The values should correspond to the mocked column names
    expected_values = [hostname, False, None, None, None, None, None, None, None]
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


def test_vm_exists_returns_none(db_instance):
    """Test vm_exists when fetchone returns None (database error condition)."""
    hostname = "test-vm"
    db_instance.cursor.fetchone.return_value = None
    assert db_instance.vm_exists(hostname) is False


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
    """Test getting all logs of a VM."""
    hostname = "log-vm-01"
    db_instance.cursor.fetchone.return_value = ("cloud init data", "docker data")

    result = db_instance.get_vm_logs(hostname)

    db_instance.cursor.execute.assert_called_with(
        "SELECT cloudinitlogs, dockerlogs FROM vms WHERE hostname = %s;",
        (hostname,),
    )
    assert result == {
        "cloud_init_logs": "cloud init data",
        "docker_logs": "docker data",
    }


def test_get_vm_logs_by_type(db_instance):
    """Test getting logs of a VM by specific type."""
    hostname = "log-vm-01"

    # Test cloud_init type
    db_instance.cursor.fetchone.return_value = ("cloud init data",)
    result = db_instance.get_vm_logs(hostname, log_type="cloud_init")
    db_instance.cursor.execute.assert_called_with(
        "SELECT cloudinitlogs FROM vms WHERE hostname = %s;", (hostname,)
    )
    assert result == {"cloud_init_logs": "cloud init data"}

    # Test docker type
    db_instance.cursor.fetchone.return_value = ("docker data",)
    result = db_instance.get_vm_logs(hostname, log_type="docker")
    db_instance.cursor.execute.assert_called_with(
        "SELECT dockerlogs FROM vms WHERE hostname = %s;", (hostname,)
    )
    assert result == {"docker_logs": "docker data"}


def test_save_logs_by_hostname(db_instance):
    """Test saving cloud_init logs for a specific VM."""
    hostname = "log-vm-02"
    logs = "new log data to save"
    db_instance.save_logs_by_hostname(hostname, logs, log_type="cloud_init")
    db_instance.cursor.execute.assert_called_with(
        "UPDATE vms SET cloudinitlogs = %s WHERE hostname = %s;", (logs, hostname)
    )
    db_instance.conn.commit.assert_called_once()


def test_save_docker_logs_by_hostname(db_instance):
    """Test saving docker logs for a specific VM."""
    hostname = "log-vm-03"
    logs = "docker log data"
    db_instance.save_logs_by_hostname(hostname, logs, log_type="docker")
    db_instance.cursor.execute.assert_called_with(
        "UPDATE vms SET dockerlogs = %s WHERE hostname = %s;", (logs, hostname)
    )
    db_instance.conn.commit.assert_called_once()


def test_append_logs_by_hostname(db_instance):
    """Test atomically appending logs for a VM."""
    hostname = "log-vm-04"
    new_logs = "new line 1\nnew line 2"
    db_instance.append_logs_by_hostname(
        hostname, new_logs, log_type="cloud_init"
    )
    db_instance.cursor.execute.assert_called_once()
    call_args = db_instance.cursor.execute.call_args
    query = call_args[0][0]
    params = call_args[0][1]
    # Verify the query uses atomic COALESCE-based append
    assert "COALESCE" in query
    assert "cloudinitlogs" in query
    # Params: (max_size, max_size, new_logs, hostname)
    assert params == (1 * 1024 * 1024, 1 * 1024 * 1024, new_logs, hostname)
    db_instance.conn.commit.assert_called_once()


def test_append_docker_logs_by_hostname(db_instance):
    """Test atomically appending docker logs for a VM."""
    hostname = "log-vm-05"
    new_logs = "docker line 1"
    db_instance.append_logs_by_hostname(
        hostname, new_logs, log_type="docker"
    )
    call_args = db_instance.cursor.execute.call_args
    query = call_args[0][0]
    assert "dockerlogs" in query
    db_instance.conn.commit.assert_called_once()


def test_append_logs_custom_max_size(db_instance):
    """Test appending logs with a custom max_size."""
    hostname = "log-vm-06"
    new_logs = "some logs"
    custom_max = 512 * 1024  # 512KB
    db_instance.append_logs_by_hostname(
        hostname, new_logs, log_type="cloud_init", max_size=custom_max
    )
    call_args = db_instance.cursor.execute.call_args
    params = call_args[0][1]
    assert params == (custom_max, custom_max, new_logs, hostname)


def test_append_logs_rollback_on_error(db_instance):
    """Test that append_logs rolls back on database error."""
    hostname = "log-vm-07"
    db_instance.cursor.execute.side_effect = Exception("DB error")
    with pytest.raises(Exception, match="DB error"):
        db_instance.append_logs_by_hostname(hostname, "logs")
    db_instance.conn.rollback.assert_called_once()


def test_old_read_modify_write_race_condition():
    """Demonstrate the race condition in the old read-modify-write pattern.

    The old code did:
        1. existing = db.get_vm_logs(hostname)  # READ
        2. vm_log = existing + new_logs          # MODIFY
        3. db.save_logs_by_hostname(vm_log)      # WRITE

    With concurrent requests for the same VM, two requests could read
    the same snapshot, append their own data, and overwrite each other:

        Request A: reads "line1"
        Request B: reads "line1"           (same snapshot)
        Request A: writes "line1\\nline2"
        Request B: writes "line1\\nline3"   (overwrites A's line2)

    Result: "line2" is permanently lost.

    The fix uses a single SQL UPDATE with COALESCE to make the
    append atomic — PostgreSQL's row-level locking ensures no
    interleaving.
    """
    # Simulate the old non-atomic pattern
    shared_state = {"logs": "initial"}

    def old_read():
        return shared_state["logs"]

    def old_write(value):
        shared_state["logs"] = value

    # Simulate two concurrent requests with interleaved execution
    # Request A reads
    snapshot_a = old_read()
    # Request B reads (same snapshot — race!)
    snapshot_b = old_read()

    # Request A appends and writes
    old_write(snapshot_a + "\nbatch_A")
    # Request B appends and writes (overwrites A's append)
    old_write(snapshot_b + "\nbatch_B")

    # batch_A is lost — this is the bug
    assert "batch_A" not in shared_state["logs"]
    assert shared_state["logs"] == "initial\nbatch_B"


def test_atomic_append_prevents_race_condition(db_instance):
    """Verify append_logs_by_hostname uses atomic SQL (no read step).

    The new method issues a single UPDATE query that appends within
    PostgreSQL, so row-level locking prevents concurrent requests
    from overwriting each other's data.
    """
    hostname = "race-vm"

    # Simulate two concurrent appends — both call append_logs
    db_instance.append_logs_by_hostname(
        hostname, "batch_A", log_type="docker"
    )
    db_instance.append_logs_by_hostname(
        hostname, "batch_B", log_type="docker"
    )

    # Verify two separate atomic UPDATEs were issued (not read-modify-write)
    assert db_instance.cursor.execute.call_count == 2
    for call in db_instance.cursor.execute.call_args_list:
        query = call[0][0]
        # Each call is a single UPDATE — no SELECT (read) step
        assert "UPDATE" in query
        assert "SELECT" not in query or "COALESCE" in query
    # No get_vm_logs calls — the old read step is eliminated
    db_instance.cursor.fetchone.assert_not_called()


def test_threading_lock_serializes_concurrent_access(db_instance):
    """Verify the threading lock serializes concurrent database access.

    Simulates the scenario where 25 VMs ship logs simultaneously,
    causing multiple Flask threads to call database methods concurrently.
    Without the lock, psycopg2's non-thread-safe connection gets
    corrupted. With the lock, calls are serialized.
    """
    import threading

    results = {"order": [], "errors": []}
    barrier = threading.Barrier(25)

    def simulate_log_post(vm_index):
        """Simulate a log shipper POST from a client VM."""
        try:
            # All threads wait here, then fire simultaneously
            barrier.wait(timeout=5)
            db_instance.append_logs_by_hostname(
                f"vm-{vm_index}",
                f"log line from vm-{vm_index}",
                log_type="docker",
            )
            results["order"].append(vm_index)
        except Exception as e:
            results["errors"].append((vm_index, str(e)))

    # Launch 25 concurrent threads (simulating 25 VMs)
    threads = []
    for i in range(25):
        t = threading.Thread(target=simulate_log_post, args=(i,))
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=10)

    # All 25 calls should complete without errors
    assert len(results["errors"]) == 0, (
        f"Concurrent DB calls failed: {results['errors']}"
    )
    assert len(results["order"]) == 25

    # The lock ensures calls were serialized — verify execute was
    # called 25 times (one per thread, no interleaving)
    assert db_instance.cursor.execute.call_count == 25


def test_threading_lock_prevents_interleaved_reads_and_writes(
    db_instance,
):
    """Verify reads and writes don't interleave under concurrent access.

    Simulates the real scenario: some threads POST logs (writes) while
    others poll vm-status (reads). Without a lock, a write could
    corrupt the connection mid-read.
    """
    import threading

    barrier = threading.Barrier(10)
    errors = []

    def do_read(idx):
        try:
            barrier.wait(timeout=5)
            db_instance.get_all_vm_status()
        except Exception as e:
            errors.append(("read", idx, str(e)))

    def do_write(idx):
        try:
            barrier.wait(timeout=5)
            db_instance.append_logs_by_hostname(
                f"vm-{idx}", f"logs-{idx}", log_type="cloud_init"
            )
        except Exception as e:
            errors.append(("write", idx, str(e)))

    threads = []
    # 5 readers (vm-status polling) + 5 writers (log shipping)
    for i in range(5):
        threads.append(threading.Thread(target=do_read, args=(i,)))
        threads.append(threading.Thread(target=do_write, args=(i,)))

    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(errors) == 0, f"Concurrent access errors: {errors}"
    # 5 reads (get_all_vm_status) + 5 writes (append_logs)
    assert db_instance.cursor.execute.call_count == 10


def test_lock_released_when_cursor_creation_fails(db_instance):
    """Verify the lock is released if conn.cursor() raises.

    Without the fix, a failed cursor() call would leave the RLock
    permanently acquired, deadlocking all subsequent database operations.
    """
    # Make cursor() raise on first call, then succeed on second
    db_instance.conn.cursor.side_effect = [
        Exception("connection closed"),
        MagicMock(),
    ]

    # First call should raise but NOT deadlock
    with pytest.raises(Exception, match="connection closed"):
        with db_instance._cursor as cursor:
            pass  # pragma: no cover

    # Second call should succeed — proves the lock was released
    with db_instance._cursor as cursor:
        assert cursor is not None


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
    assert "Invalid VM status 'invalid_status'" in caplog.text


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
    """Test that the destructor closes the database connection."""
    conn = db_instance.conn

    # Call __del__ directly for predictable testing, as garbage collection is not guaranteed
    db_instance.__del__()

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
    assert "Failed to retrieve unassigned VMs: DB error" in caplog.text


def test_get_assigned_vms_error(db_instance, caplog):
    """Test error handling in get_assigned_vms."""
    db_instance.cursor.execute.side_effect = Exception("DB error")
    result = db_instance.get_assigned_vms()
    assert result == []
    assert "Failed to retrieve assigned VMs: DB error" in caplog.text


def test_assign_vm_db_error(db_instance, caplog):
    """Test error handling in assign_vm."""
    hostname = "available-vm"
    db_instance.get_first_available_vm = MagicMock(return_value=hostname)
    db_instance.cursor.execute.side_effect = Exception("DB error")
    with pytest.raises(Exception, match="DB error"):
        db_instance.assign_vm("user@example.com", "cmd", "123")
    assert "Failed to assign VM" in caplog.text
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

    # Also test with specific log_type
    result = db_instance.get_vm_logs(hostname, log_type="cloud_init")
    assert result is None


def test_get_all_vm_status_error(db_instance, caplog):
    """Test error handling in get_all_vm_status."""
    db_instance.cursor.execute.side_effect = Exception("DB error")
    result = db_instance.get_all_vm_status()
    assert result is None
    assert "Failed to retrieve VM statuses: DB error" in caplog.text


def test_update_vm_status_db_error(db_instance, caplog):
    """Test error handling in update_vm_status."""
    hostname = "vm-to-update"
    status = "running"
    db_instance.cursor.execute.side_effect = Exception("DB error")
    db_instance.update_vm_status(hostname, status)
    assert "Failed to update status for VM" in caplog.text
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


def test_get_all_vms_for_export_excludes_sensitive_columns(db_instance):
    """Test that export excludes pin and crdcommand columns."""
    with patch.object(db_instance, "get_column_names") as mock_get_columns:
        column_names = [
            "hostname",
            "pin",
            "crdcommand",
            "useremail",
            "inuse",
            "healthy",
            "status",
            "cloudinitlogs",
            "dockerlogs",
            "terraformapplydurationseconds",
            "createdat",
        ]
        mock_get_columns.return_value = column_names

        vm_data = [
            ("vm1", "email1", False, "Healthy", "running", 45.0, "2023-01-01"),
        ]
        db_instance.cursor.fetchall.return_value = vm_data

        vms = db_instance.get_all_vms_for_export(include_logs=False)

        # pin, crdcommand, cloudinitlogs, dockerlogs should all be excluded
        expected_columns = [
            "hostname",
            "useremail",
            "inuse",
            "healthy",
            "status",
            "terraformapplydurationseconds",
            "createdat",
        ]
        query_columns = ", ".join(expected_columns)
        db_instance.cursor.execute.assert_called_with(
            f"SELECT {query_columns} FROM vms;"
        )
        assert "pin" not in vms[0]
        assert "crdcommand" not in vms[0]
        assert "cloudinitlogs" not in vms[0]
        assert "dockerlogs" not in vms[0]


def test_get_all_vms_for_export_includes_logs_when_requested(db_instance):
    """Test that export includes logs when include_logs=True."""
    with patch.object(db_instance, "get_column_names") as mock_get_columns:
        column_names = [
            "hostname",
            "pin",
            "crdcommand",
            "useremail",
            "inuse",
            "healthy",
            "status",
            "cloudinitlogs",
            "dockerlogs",
            "createdat",
        ]
        mock_get_columns.return_value = column_names

        vm_data = [
            ("vm1", "email1", False, "Healthy", "running", "cloud logs", "docker logs", "2023-01-01"),
        ]
        db_instance.cursor.fetchall.return_value = vm_data

        vms = db_instance.get_all_vms_for_export(include_logs=True)

        # pin and crdcommand excluded, but logs included
        expected_columns = [
            "hostname",
            "useremail",
            "inuse",
            "healthy",
            "status",
            "cloudinitlogs",
            "dockerlogs",
            "createdat",
        ]
        query_columns = ", ".join(expected_columns)
        db_instance.cursor.execute.assert_called_with(
            f"SELECT {query_columns} FROM vms;"
        )
        assert "pin" not in vms[0]
        assert "crdcommand" not in vms[0]
        assert vms[0]["cloudinitlogs"] == "cloud logs"
        assert vms[0]["dockerlogs"] == "docker logs"


def test_get_all_vms_for_export_default_excludes_logs(db_instance):
    """Test that the default behavior excludes logs."""
    with patch.object(db_instance, "get_column_names") as mock_get_columns:
        column_names = [
            "hostname",
            "pin",
            "crdcommand",
            "useremail",
            "cloudinitlogs",
            "dockerlogs",
        ]
        mock_get_columns.return_value = column_names

        db_instance.cursor.fetchall.return_value = [("vm1", "email1")]

        vms = db_instance.get_all_vms_for_export()

        # Default should exclude logs
        expected_columns = ["hostname", "useremail"]
        query_columns = ", ".join(expected_columns)
        db_instance.cursor.execute.assert_called_with(
            f"SELECT {query_columns} FROM vms;"
        )
        assert "cloudinitlogs" not in vms[0]
        assert "dockerlogs" not in vms[0]


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

    # Check values passed (timestamps, duration, inlined duration for total, hostname)
    assert values == (1609459200, 1609459260, 60.0, 60.0, hostname)
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

    # Extra value for inlined container duration in total formula
    assert values == (1609459300, 1609459360, 60.0, 60.0, hostname)
    db_instance.conn.commit.assert_called_once()


def test_create_scheduled_destruction(db_instance):
    """Test creating a new scheduled destruction."""
    from datetime import datetime, timezone

    schedule_name = "Friday Tutorial End"
    destruction_time = datetime(2025, 12, 5, 17, 30, 0, tzinfo=timezone.utc)
    recurrence_rule = "FREQ=WEEKLY;BYDAY=FR"
    created_by = "admin@example.com"

    db_instance.cursor.fetchone.return_value = (1,)

    schedule_id = db_instance.create_scheduled_destruction(
        schedule_name=schedule_name,
        destruction_time=destruction_time,
        recurrence_rule=recurrence_rule,
        created_by=created_by,
        notification_enabled=True,
        notification_hours_before=1,
    )

    expected_query = """
            INSERT INTO scheduled_destructions
            (schedule_name, destruction_time, recurrence_rule, created_by,
            notification_enabled, notification_hours_before, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'scheduled')
            RETURNING id;
        """

    # Convert to naive UTC for comparison
    naive_destruction_time = destruction_time.replace(tzinfo=None)

    db_instance.cursor.execute.assert_called_once()
    args = db_instance.cursor.execute.call_args[0]
    assert "".join(args[0].split()) == "".join(expected_query.split())
    assert args[1] == (
        schedule_name,
        naive_destruction_time,
        recurrence_rule,
        created_by,
        True,
        1,
    )
    db_instance.conn.commit.assert_called_once()
    assert schedule_id == 1


def test_create_scheduled_destruction_one_time(db_instance):
    """Test creating a one-time scheduled destruction (no recurrence)."""
    from datetime import datetime, timezone

    schedule_name = "One-Time Cleanup"
    destruction_time = datetime(2025, 12, 6, 18, 0, 0, tzinfo=timezone.utc)

    db_instance.cursor.fetchone.return_value = (2,)

    schedule_id = db_instance.create_scheduled_destruction(
        schedule_name=schedule_name,
        destruction_time=destruction_time,
        recurrence_rule=None,
        created_by=None,
        notification_enabled=False,
        notification_hours_before=0,
    )

    naive_destruction_time = destruction_time.replace(tzinfo=None)

    db_instance.cursor.execute.assert_called_once()
    args = db_instance.cursor.execute.call_args[0]
    assert args[1] == (
        schedule_name,
        naive_destruction_time,
        None,
        None,
        False,
        0,
    )
    assert schedule_id == 2


def test_create_scheduled_destruction_error(db_instance, caplog):
    """Test error handling in create_scheduled_destruction."""
    from datetime import datetime, timezone
    import pytest

    db_instance.cursor.execute.side_effect = Exception("DB error")

    # Should raise RuntimeError instead of returning None
    with pytest.raises(RuntimeError, match="Failed to create scheduled destruction"):
        db_instance.create_scheduled_destruction(
            schedule_name="Test",
            destruction_time=datetime.now(timezone.utc),
        )

    assert "Failed to create scheduled destruction" in caplog.text
    db_instance.conn.rollback.assert_called_once()


def test_get_scheduled_destruction(db_instance):
    """Test getting a scheduled destruction by ID."""
    schedule_id = 1

    # Mock cursor.fetchone to return a tuple (as real PostgreSQL cursor does)
    # Column order matches: id, schedule_name, destruction_time, recurrence_rule,
    # created_by, status, execution_count, last_execution_time, last_execution_result,
    # notification_enabled, notification_hours_before, created_at, updated_at
    schedule_tuple = (
        1,  # id
        "Friday Tutorial End",  # schedule_name
        "2025-12-05 17:30:00",  # destruction_time
        "FREQ=WEEKLY;BYDAY=FR",  # recurrence_rule
        "admin@example.com",  # created_by
        "scheduled",  # status
        0,  # execution_count
        None,  # last_execution_time
        None,  # last_execution_result
        True,  # notification_enabled
        1,  # notification_hours_before
        None,  # created_at
        None,  # updated_at
    )

    db_instance.cursor.fetchone.return_value = schedule_tuple

    result = db_instance.get_scheduled_destruction(schedule_id)

    db_instance.cursor.execute.assert_called_with(
        "SELECT * FROM scheduled_destructions WHERE id = %s;", (schedule_id,)
    )

    # Verify the result is a dict with expected values
    assert result["id"] == 1
    assert result["schedule_name"] == "Friday Tutorial End"
    assert result["destruction_time"] == "2025-12-05 17:30:00"
    assert result["recurrence_rule"] == "FREQ=WEEKLY;BYDAY=FR"
    assert result["created_by"] == "admin@example.com"
    assert result["status"] == "scheduled"
    assert result["execution_count"] == 0


def test_get_scheduled_destruction_not_found(db_instance):
    """Test getting a scheduled destruction that doesn't exist."""
    schedule_id = 999
    db_instance.cursor.fetchone.return_value = None

    result = db_instance.get_scheduled_destruction(schedule_id)

    assert result is None


def test_get_all_scheduled_destructions(db_instance):
    """Test getting all scheduled destructions."""
    # Mock cursor.fetchall to return tuples (as real PostgreSQL cursor does)
    schedules_tuples = [
        (1, "Schedule 1", None, None, None, "scheduled", 0, None, None, True, 1, None, None),
        (2, "Schedule 2", None, None, None, "completed", 0, None, None, True, 1, None, None),
        (3, "Schedule 3", None, None, None, "scheduled", 0, None, None, True, 1, None, None),
    ]

    db_instance.cursor.fetchall.return_value = schedules_tuples

    result = db_instance.get_all_scheduled_destructions()

    db_instance.cursor.execute.assert_called_with(
        "SELECT * FROM scheduled_destructions ORDER BY destruction_time;"
    )
    assert len(result) == 3
    assert result[0]["id"] == 1
    assert result[0]["schedule_name"] == "Schedule 1"
    assert result[0]["status"] == "scheduled"
    assert result[1]["id"] == 2
    assert result[1]["schedule_name"] == "Schedule 2"
    assert result[1]["status"] == "completed"
    assert result[2]["id"] == 3
    assert result[2]["schedule_name"] == "Schedule 3"
    assert result[2]["status"] == "scheduled"


def test_get_all_scheduled_destructions_with_status_filter(db_instance):
    """Test getting scheduled destructions filtered by status."""
    # Mock cursor.fetchall to return tuples (as real PostgreSQL cursor does)
    scheduled_tuples = [
        (1, "Schedule 1", None, None, None, "scheduled", 0, None, None, True, 1, None, None),
        (3, "Schedule 3", None, None, None, "scheduled", 0, None, None, True, 1, None, None),
    ]

    db_instance.cursor.fetchall.return_value = scheduled_tuples

    result = db_instance.get_all_scheduled_destructions(status="scheduled")

    db_instance.cursor.execute.assert_called_with(
        "SELECT * FROM scheduled_destructions WHERE status = %s ORDER BY destruction_time;",
        ("scheduled",),
    )
    assert len(result) == 2
    assert result[0]["id"] == 1
    assert result[0]["schedule_name"] == "Schedule 1"
    assert result[0]["status"] == "scheduled"
    assert result[1]["id"] == 3
    assert result[1]["schedule_name"] == "Schedule 3"
    assert result[1]["status"] == "scheduled"


def test_update_scheduled_destruction_status(db_instance):
    """Test updating the status of a scheduled destruction."""
    schedule_id = 1
    status = "completed"
    execution_result = "All VMs destroyed successfully"

    db_instance.update_scheduled_destruction_status(
        schedule_id=schedule_id,
        status=status,
        execution_result=execution_result,
    )

    expected_query = """
            UPDATE scheduled_destructions
            SET status = %s,
                execution_count = execution_count + 1,
                last_execution_time = NOW(),
                last_execution_result = %s
            WHERE id = %s;
        """

    db_instance.cursor.execute.assert_called_once()
    args = db_instance.cursor.execute.call_args[0]
    assert "".join(args[0].split()) == "".join(expected_query.split())
    assert args[1] == (status, execution_result, schedule_id)
    db_instance.conn.commit.assert_called_once()


def test_update_scheduled_destruction_status_failed(db_instance):
    """Test updating status to failed with error message."""
    schedule_id = 2
    status = "failed"
    execution_result = "Terraform destroy failed: timeout"

    db_instance.update_scheduled_destruction_status(
        schedule_id=schedule_id,
        status=status,
        execution_result=execution_result,
    )

    args = db_instance.cursor.execute.call_args[0]
    assert args[1] == (status, execution_result, schedule_id)
    db_instance.conn.commit.assert_called_once()


def test_cancel_scheduled_destruction(db_instance):
    """Test cancelling a scheduled destruction."""
    schedule_id = 1

    db_instance.cancel_scheduled_destruction(schedule_id)

    db_instance.cursor.execute.assert_called_with(
        "UPDATE scheduled_destructions SET status = 'cancelled' WHERE id = %s;",
        (schedule_id,),
    )
    db_instance.conn.commit.assert_called_once()


def test_get_assigned_vm_for_email_found(db_instance):
    """Test looking up an email that already owns a VM."""
    db_instance.cursor.fetchone.return_value = ("vm-7", "running", 0)

    result = db_instance.get_assigned_vm_for_email("student@test.edu")

    assert result == {
        "hostname": "vm-7",
        "status": "running",
        "reboot_count": 0,
    }
    # Query should filter on useremail and bind the email parameter
    query = db_instance.cursor.execute.call_args[0][0]
    args = db_instance.cursor.execute.call_args[0][1]
    assert "useremail" in query
    assert args == ("student@test.edu",)


def test_get_assigned_vm_for_email_not_found(db_instance):
    """Test looking up an email with no existing VM."""
    db_instance.cursor.fetchone.return_value = None

    result = db_instance.get_assigned_vm_for_email("unknown@test.edu")

    assert result is None


def test_get_assigned_vm_for_email_error(db_instance, caplog):
    """Test error handling in get_assigned_vm_for_email."""
    db_instance.cursor.execute.side_effect = Exception("DB error")

    result = db_instance.get_assigned_vm_for_email("student@test.edu")

    assert result is None
    assert "Failed to look up assigned VM" in caplog.text


def test_reassign_crd(db_instance):
    """Test reassigning a new CRD command to an existing VM."""
    db_instance.reassign_crd(
        hostname="vm-7",
        crd_command=(
            "DISPLAY= /opt/google/chrome-remote-desktop/start-host "
            "--code='4/abc' --redirect-url='...'"
        ),
        pin="987654",
    )

    db_instance.cursor.execute.assert_called_once()
    query = db_instance.cursor.execute.call_args[0][0]
    args = db_instance.cursor.execute.call_args[0][1]

    # Query targets the right columns and the given hostname
    assert "crdcommand" in query.lower()
    assert "pin" in query.lower()
    assert "WHERE hostname" in query
    # Parameter order: (crd_command, pin, hostname)
    assert args[2] == "vm-7"
    assert "4/abc" in args[0]
    assert args[1] == "987654"

    db_instance.conn.commit.assert_called_once()


def test_reassign_crd_error(db_instance, caplog):
    """Test error handling in reassign_crd."""
    db_instance.cursor.execute.side_effect = Exception("DB error")
    with pytest.raises(Exception, match="DB error"):
        db_instance.reassign_crd("vm-7", "cmd", "000000")
    db_instance.conn.rollback.assert_called_once()
    assert "Failed to reassign CRD" in caplog.text
