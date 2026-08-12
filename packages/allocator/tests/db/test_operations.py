"""Tests for OperationsDatabase.

psycopg2-binary is a real dependency of this package (see pyproject.toml),
so unlike test_database.py these tests use the real psycopg2.IntegrityError
directly rather than mocking the psycopg2 module — OperationsDatabase takes
a plain pool object and never calls psycopg2.pool.ThreadedConnectionPool
itself, so there's no real-connection risk to guard against here.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import psycopg2
import pytest

from lablink_allocator_service.db.operations import (
    OperationInProgress,
    OperationsDatabase,
)


@pytest.fixture
def mock_pool_and_cursor():
    """Fixture returning (mock_conn, mock_cursor, mock_pool), wired so
    mock_pool.getconn() -> mock_conn -> .cursor() -> mock_cursor."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_pool = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    return mock_conn, mock_cursor, mock_pool


@pytest.fixture
def operations_db(mock_pool_and_cursor):
    """OperationsDatabase wired to a mocked pool, with a `.cursor` alias
    for test assertions (mirrors test_database.py's db_instance fixture)."""
    _, mock_cursor, mock_pool = mock_pool_and_cursor
    db = OperationsDatabase(pool=mock_pool)
    db.cursor = mock_cursor
    return db


def test_create_operation_returns_id(operations_db):
    operations_db.cursor.fetchone.return_value = (7,)

    operation_id = operations_db.create_operation(
        op_type="destroy", params=None, created_by="admin"
    )

    assert operation_id == 7
    args = operations_db.cursor.execute.call_args[0]
    expected_query = """
            INSERT INTO operations (op_type, status, params, created_by)
            VALUES (%s, 'queued', %s, %s)
            RETURNING id;
        """
    assert "".join(args[0].split()) == "".join(expected_query.split())
    assert args[1] == ("destroy", None, "admin")


def test_create_operation_raises_operation_in_progress_with_existing_job_id(
    operations_db,
):
    operations_db.cursor.execute.side_effect = [
        psycopg2.IntegrityError(
            'duplicate key value violates unique constraint '
            '"operations_single_flight"'
        ),
        None,  # the SELECT inside get_in_progress_operation
    ]
    operations_db.cursor.fetchone.return_value = (
        5, "destroy", "running", None, "admin",
        None, None, None, None, None,
    )

    with pytest.raises(OperationInProgress) as exc_info:
        operations_db.create_operation(
            op_type="apply", params=None, created_by="admin"
        )

    assert exc_info.value.job_id == 5


def test_create_operation_raises_runtime_error_when_in_progress_operation_vanishes(
    operations_db,
):
    operations_db.cursor.execute.side_effect = [
        psycopg2.IntegrityError(
            'duplicate key value violates unique constraint '
            '"operations_single_flight"'
        ),
        None,  # the SELECT inside get_in_progress_operation
    ]
    operations_db.cursor.fetchone.return_value = None

    with pytest.raises(RuntimeError):
        operations_db.create_operation(
            op_type="apply", params=None, created_by="admin"
        )


def test_get_operation_returns_dict(operations_db):
    operations_db.cursor.fetchone.return_value = (
        3, "apply", "succeeded", '{"num_vms": 2}', "admin",
        "2026-07-17 10:00:00", "2026-07-17 10:00:01",
        "2026-07-17 10:02:00", "apply output", None,
    )

    operation = operations_db.get_operation(3)

    operations_db.cursor.execute.assert_called_with(
        "SELECT * FROM operations WHERE id = %s;", (3,)
    )
    assert operation["id"] == 3
    assert operation["op_type"] == "apply"
    assert operation["status"] == "succeeded"
    assert operation["output"] == "apply output"


def test_get_operation_returns_none_when_missing(operations_db):
    operations_db.cursor.fetchone.return_value = None

    assert operations_db.get_operation(999) is None


def test_list_operations_returns_dicts_newest_first(operations_db):
    operations_db.cursor.fetchall.return_value = [
        (2, "destroy", "succeeded", None, "admin",
         "2026-07-17 11:00:00", "2026-07-17 11:00:01",
         "2026-07-17 11:03:00", "destroy output", None),
        (1, "apply", "succeeded", '{"num_vms": 1}', "admin",
         "2026-07-17 10:00:00", "2026-07-17 10:00:01",
         "2026-07-17 10:02:00", "apply output", None),
    ]

    operations = operations_db.list_operations(limit=50)

    args = operations_db.cursor.execute.call_args[0]
    expected_query = (
        "SELECT * FROM operations ORDER BY created_at DESC LIMIT %s;"
    )
    assert "".join(args[0].split()) == "".join(expected_query.split())
    assert args[1] == (50,)
    assert [o["id"] for o in operations] == [2, 1]


def test_get_in_progress_operation_returns_row(operations_db):
    operations_db.cursor.fetchone.return_value = (
        9, "destroy", "running", None, "admin",
        "2026-07-17 12:00:00", "2026-07-17 12:00:01", None, None, None,
    )

    operation = operations_db.get_in_progress_operation()

    args = operations_db.cursor.execute.call_args[0]
    expected_query = (
        "SELECT * FROM operations "
        "WHERE status IN ('queued', 'running') "
        "ORDER BY created_at DESC LIMIT 1;"
    )
    assert "".join(args[0].split()) == "".join(expected_query.split())
    assert operation["id"] == 9
    assert operation["status"] == "running"


def test_get_in_progress_operation_returns_none_when_idle(operations_db):
    operations_db.cursor.fetchone.return_value = None

    assert operations_db.get_in_progress_operation() is None


def test_start_operation_updates_status_and_started_at(operations_db):
    operations_db.start_operation(4)

    args = operations_db.cursor.execute.call_args[0]
    expected_query = (
        "UPDATE operations SET status = 'running', started_at = NOW() "
        "WHERE id = %s;"
    )
    assert "".join(args[0].split()) == "".join(expected_query.split())
    assert args[1] == (4,)


_FINISH_OPERATION_QUERY = """
            UPDATE operations
            SET status = %s, output = %s, error = %s, finished_at = NOW(),
                resources_completed = CASE
                    WHEN %s = 'succeeded' AND resources_total IS NOT NULL
                    THEN resources_total
                    ELSE resources_completed
                END
            WHERE id = %s;
        """


def test_finish_operation_succeeded(operations_db):
    operations_db.finish_operation(4, status="succeeded", output="tofu output")

    args = operations_db.cursor.execute.call_args[0]
    assert "".join(args[0].split()) == "".join(_FINISH_OPERATION_QUERY.split())
    assert args[1] == ("succeeded", "tofu output", None, "succeeded", 4)


def test_finish_operation_failed(operations_db):
    operations_db.finish_operation(4, status="failed", error="tofu exploded")

    args = operations_db.cursor.execute.call_args[0]
    assert "".join(args[0].split()) == "".join(_FINISH_OPERATION_QUERY.split())
    assert args[1] == ("failed", None, "tofu exploded", "failed", 4)


def test_sweep_interrupted_operations_returns_count(operations_db):
    operations_db.cursor.fetchall.return_value = [(1,), (2,)]

    count = operations_db.sweep_interrupted_operations()

    args = operations_db.cursor.execute.call_args[0]
    expected_query = """
            UPDATE operations
            SET status = 'interrupted', finished_at = NOW()
            WHERE status IN ('queued', 'running')
            RETURNING id;
        """
    assert "".join(args[0].split()) == "".join(expected_query.split())
    assert count == 2


def test_sweep_interrupted_operations_returns_zero_when_none_in_progress(
    operations_db,
):
    operations_db.cursor.fetchall.return_value = []

    assert operations_db.sweep_interrupted_operations() == 0


def test_update_operation_progress_executes_expected_query(operations_db):
    operations_db.update_operation_progress(7, completed=3, total=8)

    args = operations_db.cursor.execute.call_args[0]
    expected_query = """
            UPDATE operations
            SET resources_completed = %s, resources_total = %s
            WHERE id = %s;
        """
    assert "".join(args[0].split()) == "".join(expected_query.split())
    assert args[1] == (3, 8, 7)


def test_finish_operation_succeeded_passes_status_twice_for_case_guard(operations_db):
    """finish_operation's UPDATE uses a SQL CASE keyed on status to snap
    resources_completed to resources_total only when status='succeeded' —
    this test verifies the query shape and that `status` is bound both as
    the SET value and as the CASE condition; the CASE branching itself is
    SQL semantics, not something a mocked cursor can prove, matching this
    file's existing style of asserting query shape + params."""
    operations_db.finish_operation(7, status="succeeded", output="ok")

    args = operations_db.cursor.execute.call_args[0]
    assert "".join(args[0].split()) == "".join(_FINISH_OPERATION_QUERY.split())
    assert args[1] == ("succeeded", "ok", None, "succeeded", 7)


def test_finish_operation_failed_passes_status_twice_for_case_guard(operations_db):
    operations_db.finish_operation(7, status="failed", error="boom")

    args = operations_db.cursor.execute.call_args[0]
    assert "".join(args[0].split()) == "".join(_FINISH_OPERATION_QUERY.split())
    assert args[1] == ("failed", None, "boom", "failed", 7)


def test_get_operation_includes_progress_columns(operations_db):
    """A regression guard for _OPERATION_COLUMNS: get_operation's dict
    construction (dict(zip(_OPERATION_COLUMNS, row))) must stay in sync
    with the CREATE TABLE column order — this proves the two new columns
    actually surface in the returned dict, not just that the SQL text
    looks right."""
    operations_db.cursor.fetchone.return_value = (
        7, "apply", "running", None, "admin",
        None, None, None, None, None, 8, 3,
    )
    operation = operations_db.get_operation(7)
    assert operation["resources_total"] == 8
    assert operation["resources_completed"] == 3
