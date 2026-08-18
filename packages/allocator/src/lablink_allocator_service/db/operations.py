"""Persistence for the operations table (on-demand apply/destroy jobs).

A standalone class rather than more methods on VmDatabase: the
operations table has no foreign-key or column coupling to the vms table
(unlike the AdminReservedAt admin-reservation columns, which reach
directly into VM rows), so there's no reason for it to share
VmDatabase's god-class surface. It shares the same connection
pool (see VmDatabase.pool) rather than opening a second one,
since POOL_MAX_SIZE is already tuned for this allocator's total
connection budget.
"""
from __future__ import annotations

import logging
from typing import List, Optional

import psycopg2

from lablink_allocator_service.db.pool import PooledCursor

logger = logging.getLogger(__name__)


class OperationInProgress(Exception):
    """Raised by create_operation when another operation is already
    queued/running — the operations_single_flight partial unique index
    was violated."""

    def __init__(self, job_id: int):
        self.job_id = job_id
        super().__init__(
            f"An operation is already in progress (job #{job_id})"
        )


class OperationsDatabase:
    """Persistence for the operations table.

    Args:
        pool: A psycopg2 connection pool, shared with VmDatabase
            (see VmDatabase.pool) rather than owned here.
    """

    def __init__(self, pool):
        self._pool = pool

    @property
    def _cursor(self):
        """Return a context manager that checks out a pooled connection
        and yields a dict-rows cursor (rows keyed by the database's own
        column names). See db.pool.PooledCursor."""
        return PooledCursor(self._pool, dict_rows=True)

    def create_operation(
        self,
        op_type: str,
        params: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> int:
        """Create a queued operation and return its ID.

        Raises:
            OperationInProgress: if another operation is already
                queued/running (operations_single_flight guard).
            RuntimeError: if the INSERT fails on the single-flight guard
                but the in-progress operation has since vanished (an
                unusual race between the failed insert and the
                get_in_progress_operation lookup, e.g. the colliding
                operation finished in between).
        """
        query = """
            INSERT INTO operations (op_type, status, params, created_by)
            VALUES (%s, 'queued', %s, %s)
            RETURNING id;
        """
        with self._cursor as cursor:
            try:
                cursor.execute(query, (op_type, params, created_by))
                operation_id = cursor.fetchone()["id"]
                logger.info(
                    "Created operation #%d (%s)", operation_id, op_type
                )
                return operation_id
            except psycopg2.IntegrityError as e:
                existing = self.get_in_progress_operation()
                if existing is not None:
                    raise OperationInProgress(job_id=existing["id"]) from e
                raise RuntimeError(
                    f"Failed to create operation: {e}"
                ) from e

    def get_operation(self, operation_id: int) -> Optional[dict]:
        """Get an operation by ID."""
        query = "SELECT * FROM operations WHERE id = %s;"
        with self._cursor as cursor:
            cursor.execute(query, (operation_id,))
            row = cursor.fetchone()
        return dict(row) if row else None

    def list_operations(self, limit: int = 50) -> List[dict]:
        """List recent operations, newest first."""
        query = "SELECT * FROM operations ORDER BY created_at DESC LIMIT %s;"
        with self._cursor as cursor:
            cursor.execute(query, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def get_in_progress_operation(self) -> Optional[dict]:
        """Return the currently queued/running operation, if any.

        The operations_single_flight partial unique index guarantees at
        most one row can match; LIMIT 1 is defensive, not load-bearing.
        """
        query = (
            "SELECT * FROM operations "
            "WHERE status IN ('queued', 'running') "
            "ORDER BY created_at DESC LIMIT 1;"
        )
        with self._cursor as cursor:
            cursor.execute(query)
            row = cursor.fetchone()
        return dict(row) if row else None

    def start_operation(self, operation_id: int) -> None:
        """Mark an operation running."""
        query = (
            "UPDATE operations SET status = 'running', started_at = NOW() "
            "WHERE id = %s;"
        )
        with self._cursor as cursor:
            cursor.execute(query, (operation_id,))

    def update_operation_progress(
        self, operation_id: int, completed: int, total: int
    ) -> None:
        """Update an operation's incremental resource-completion progress.
        Called from OperationsWorker as resources finish creating/
        destroying during a launch/destroy job still in `running` status.
        """
        query = """
            UPDATE operations
            SET resources_completed = %s, resources_total = %s
            WHERE id = %s;
        """
        with self._cursor as cursor:
            cursor.execute(query, (completed, total, operation_id))

    def finish_operation(
        self,
        operation_id: int,
        status: str,
        output: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Mark an operation succeeded or failed. A successful finish also
        snaps resources_completed to resources_total (if a total was ever
        recorded), so a completed job never displays a stale partial count
        from a missed final progress update."""
        query = """
            UPDATE operations
            SET status = %s, output = %s, error = %s, finished_at = NOW(),
                resources_completed = CASE
                    WHEN %s = 'succeeded' AND resources_total IS NOT NULL
                    THEN resources_total
                    ELSE resources_completed
                END
            WHERE id = %s;
        """
        with self._cursor as cursor:
            cursor.execute(
                query, (status, output, error, status, operation_id)
            )

    def sweep_interrupted_operations(self) -> int:
        """Mark any queued/running operation as interrupted.

        Called once at allocator startup: a row still queued/running means
        the allocator process died mid-job last time, so the OpenTofu
        subprocess died with it. Returns the number of rows affected.
        """
        query = """
            UPDATE operations
            SET status = 'interrupted', finished_at = NOW()
            WHERE status IN ('queued', 'running')
            RETURNING id;
        """
        with self._cursor as cursor:
            cursor.execute(query)
            return len(cursor.fetchall())
