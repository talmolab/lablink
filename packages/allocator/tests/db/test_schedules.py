"""Tests for ScheduleDatabase (persistence for the scheduled_destructions
table).

`schedule_db_instance`/`mock_db_connection` fixtures live in
tests/db/conftest.py — the same mocked-pool pattern as db_instance in
test_vms.py, just wired to ScheduleDatabase instead of VmDatabase.
"""


def test_create_scheduled_destruction(schedule_db_instance):
    """Test creating a new scheduled destruction."""
    from datetime import datetime, timezone

    schedule_name = "Friday Tutorial End"
    destruction_time = datetime(2025, 12, 5, 17, 30, 0, tzinfo=timezone.utc)
    recurrence_rule = "FREQ=WEEKLY;BYDAY=FR"
    created_by = "admin@example.com"

    schedule_db_instance.cursor.fetchone.return_value = {"id": 1}

    schedule_id = schedule_db_instance.create_scheduled_destruction(
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

    schedule_db_instance.cursor.execute.assert_called_once()
    args = schedule_db_instance.cursor.execute.call_args[0]
    assert "".join(args[0].split()) == "".join(expected_query.split())
    assert args[1] == (
        schedule_name,
        naive_destruction_time,
        recurrence_rule,
        created_by,
        True,
        1,
    )
    assert schedule_id == 1


def test_create_scheduled_destruction_one_time(schedule_db_instance):
    """Test creating a one-time scheduled destruction (no recurrence)."""
    from datetime import datetime, timezone

    schedule_name = "One-Time Cleanup"
    destruction_time = datetime(2025, 12, 6, 18, 0, 0, tzinfo=timezone.utc)

    schedule_db_instance.cursor.fetchone.return_value = {"id": 2}

    schedule_id = schedule_db_instance.create_scheduled_destruction(
        schedule_name=schedule_name,
        destruction_time=destruction_time,
        recurrence_rule=None,
        created_by=None,
        notification_enabled=False,
        notification_hours_before=0,
    )

    naive_destruction_time = destruction_time.replace(tzinfo=None)

    schedule_db_instance.cursor.execute.assert_called_once()
    args = schedule_db_instance.cursor.execute.call_args[0]
    assert args[1] == (
        schedule_name,
        naive_destruction_time,
        None,
        None,
        False,
        0,
    )
    assert schedule_id == 2


def test_create_scheduled_destruction_error(schedule_db_instance, caplog):
    """Test error handling in create_scheduled_destruction."""
    from datetime import datetime, timezone
    import pytest

    schedule_db_instance.cursor.execute.side_effect = Exception("DB error")

    # Should raise RuntimeError instead of returning None
    with pytest.raises(RuntimeError, match="Failed to create scheduled destruction"):
        schedule_db_instance.create_scheduled_destruction(
            schedule_name="Test",
            destruction_time=datetime.now(timezone.utc),
        )

    assert "Failed to create scheduled destruction" in caplog.text


def test_get_scheduled_destruction(schedule_db_instance):
    """Test getting a scheduled destruction by ID."""
    schedule_id = 1

    # Mock cursor.fetchone to return a tuple (as real PostgreSQL cursor does)
    schedule_row = {
        "id": 1,
        "schedule_name": "Friday Tutorial End",
        "destruction_time": "2025-12-05 17:30:00",
        "recurrence_rule": "FREQ=WEEKLY;BYDAY=FR",
        "created_by": "admin@example.com",
        "status": "scheduled",
        "execution_count": 0,
        "last_execution_time": None,
        "last_execution_result": None,
        "notification_enabled": True,
        "notification_hours_before": 1,
        "created_at": None,
        "updated_at": None,
    }

    schedule_db_instance.cursor.fetchone.return_value = schedule_row

    result = schedule_db_instance.get_scheduled_destruction(schedule_id)

    schedule_db_instance.cursor.execute.assert_called_with(
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


def test_get_scheduled_destruction_not_found(schedule_db_instance):
    """Test getting a scheduled destruction that doesn't exist."""
    schedule_id = 999
    schedule_db_instance.cursor.fetchone.return_value = None

    result = schedule_db_instance.get_scheduled_destruction(schedule_id)

    assert result is None


def test_get_all_scheduled_destructions(schedule_db_instance):
    """Test getting all scheduled destructions."""
    # Dict rows, as the RealDictCursor returns them.
    schedule_rows = [
        {"id": 1, "schedule_name": "Schedule 1", "status": "scheduled"},
        {"id": 2, "schedule_name": "Schedule 2", "status": "completed"},
        {"id": 3, "schedule_name": "Schedule 3", "status": "scheduled"},
    ]

    schedule_db_instance.cursor.fetchall.return_value = schedule_rows

    result = schedule_db_instance.get_all_scheduled_destructions()

    schedule_db_instance.cursor.execute.assert_called_with(
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


def test_get_all_scheduled_destructions_with_status_filter(schedule_db_instance):
    """Test getting scheduled destructions filtered by status."""
    # Dict rows, as the RealDictCursor returns them.
    scheduled_rows = [
        {"id": 1, "schedule_name": "Schedule 1", "status": "scheduled"},
        {"id": 3, "schedule_name": "Schedule 3", "status": "scheduled"},
    ]

    schedule_db_instance.cursor.fetchall.return_value = scheduled_rows

    result = schedule_db_instance.get_all_scheduled_destructions(status="scheduled")

    schedule_db_instance.cursor.execute.assert_called_with(
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


def test_update_scheduled_destruction_status(schedule_db_instance):
    """Test updating the status of a scheduled destruction."""
    schedule_id = 1
    status = "completed"
    execution_result = "All VMs destroyed successfully"

    schedule_db_instance.update_scheduled_destruction_status(
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

    schedule_db_instance.cursor.execute.assert_called_once()
    args = schedule_db_instance.cursor.execute.call_args[0]
    assert "".join(args[0].split()) == "".join(expected_query.split())
    assert args[1] == (status, execution_result, schedule_id)


def test_update_scheduled_destruction_status_failed(schedule_db_instance):
    """Test updating status to failed with error message."""
    schedule_id = 2
    status = "failed"
    execution_result = "OpenTofu destroy failed: timeout"

    schedule_db_instance.update_scheduled_destruction_status(
        schedule_id=schedule_id,
        status=status,
        execution_result=execution_result,
    )

    args = schedule_db_instance.cursor.execute.call_args[0]
    assert args[1] == (status, execution_result, schedule_id)


def test_cancel_scheduled_destruction(schedule_db_instance):
    """Test cancelling a scheduled destruction."""
    schedule_id = 1

    schedule_db_instance.cancel_scheduled_destruction(schedule_id)

    schedule_db_instance.cursor.execute.assert_called_with(
        "UPDATE scheduled_destructions SET status = 'cancelled' WHERE id = %s;",
        (schedule_id,),
    )
