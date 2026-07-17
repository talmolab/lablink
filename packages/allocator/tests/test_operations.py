"""Tests for OperationsWorker."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from lablink_allocator_service.operations import OperationsWorker
from lablink_allocator_service.operations_db import OperationInProgress


@pytest.fixture
def mock_database():
    """Stand-in for OperationsDatabase — OperationsWorker only calls the
    four methods asserted below, so a plain MagicMock is sufficient."""
    return MagicMock()


@pytest.fixture
def worker(mock_database):
    return OperationsWorker(database=mock_database)


def _wait_until(predicate, timeout_s=1.0, interval_s=0.01):
    """Poll predicate() until it's truthy or timeout_s elapses."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval_s)
    return False


def test_start_sweeps_interrupted_operations(worker, mock_database):
    mock_database.sweep_interrupted_operations.return_value = 2

    worker.start()

    mock_database.sweep_interrupted_operations.assert_called_once()


def test_submit_creates_queued_operation_and_returns_id(worker, mock_database):
    mock_database.create_operation.return_value = 17
    fn = MagicMock(return_value="done")

    job_id = worker.submit(
        op_type="destroy", fn=fn, params=None, created_by="admin"
    )

    assert job_id == 17
    mock_database.create_operation.assert_called_once_with(
        op_type="destroy", params=None, created_by="admin"
    )


def test_submit_propagates_operation_in_progress(worker, mock_database):
    mock_database.create_operation.side_effect = OperationInProgress(job_id=5)

    with pytest.raises(OperationInProgress) as exc_info:
        worker.submit(
            op_type="apply", fn=MagicMock(), params=None, created_by="admin"
        )

    assert exc_info.value.job_id == 5


def test_submit_runs_fn_on_background_thread_and_marks_succeeded(
    worker, mock_database
):
    mock_database.create_operation.return_value = 1
    fn = MagicMock(return_value="terraform output")

    worker.submit(op_type="destroy", fn=fn, params=None, created_by="admin")

    assert _wait_until(lambda: mock_database.finish_operation.called)
    mock_database.start_operation.assert_called_once_with(1)
    fn.assert_called_once()
    mock_database.finish_operation.assert_called_once_with(
        1, status="succeeded", output="terraform output"
    )


def test_submit_marks_failed_when_fn_raises(worker, mock_database):
    mock_database.create_operation.return_value = 2
    fn = MagicMock(side_effect=RuntimeError("terraform exploded"))

    worker.submit(op_type="apply", fn=fn, params=None, created_by="admin")

    assert _wait_until(lambda: mock_database.finish_operation.called)
    mock_database.finish_operation.assert_called_once_with(
        2, status="failed", error="terraform exploded"
    )


def test_submit_marks_failed_when_start_operation_raises(worker, mock_database):
    """If start_operation itself blows up, the row must still be marked
    failed instead of staying stuck at status='queued' forever (which
    would make the single-flight guard reject all future submits)."""
    mock_database.create_operation.return_value = 4
    mock_database.start_operation.side_effect = RuntimeError("db exploded")
    fn = MagicMock(return_value="unused")

    worker.submit(op_type="apply", fn=fn, params=None, created_by="admin")

    assert _wait_until(lambda: mock_database.finish_operation.called)
    fn.assert_not_called()
    mock_database.finish_operation.assert_called_once_with(
        4, status="failed", error="db exploded"
    )


def test_submit_does_not_block_caller_on_slow_fn(worker, mock_database):
    """The whole point of this worker: submit() returns before fn() finishes."""
    mock_database.create_operation.return_value = 3
    started = time.monotonic()

    def slow_fn():
        time.sleep(0.3)
        return "done"

    worker.submit(op_type="destroy", fn=slow_fn, params=None, created_by="admin")

    elapsed = time.monotonic() - started
    assert elapsed < 0.3, (
        f"submit() blocked for {elapsed:.2f}s waiting on fn() — "
        f"it must return immediately"
    )
