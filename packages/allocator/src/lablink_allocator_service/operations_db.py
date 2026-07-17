"""Persistence for the operations table (on-demand apply/destroy jobs).

A standalone class rather than more methods on PostgresqlDatabase: the
operations table has no foreign-key or column coupling to the vms table
(unlike scheduled_destructions or the AdminReservedAt admin-reservation
columns, which reach directly into VM rows), so there's no reason for it
to share PostgresqlDatabase's god-class surface. It shares the same
connection pool (see PostgresqlDatabase.pool) rather than opening a
second one, since POOL_MAX_SIZE is already tuned for this allocator's
total connection budget.
"""
from __future__ import annotations

import logging
from typing import List, Optional

import psycopg2

from lablink_allocator_service.database import _PooledCursor

logger = logging.getLogger(__name__)

# Named-key contract for rows returned by the SELECT * queries below. Every
# query in this class must emit columns in this order (matches the
# CREATE TABLE column order in generate_init_sql.py).
_OPERATION_COLUMNS = (
    "id",
    "op_type",
    "status",
    "params",
    "created_by",
    "created_at",
    "started_at",
    "finished_at",
    "output",
    "error",
)


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
        pool: A psycopg2 connection pool, shared with PostgresqlDatabase
            (see PostgresqlDatabase.pool) rather than owned here.
    """

    def __init__(self, pool):
        self._pool = pool

    @property
    def _cursor(self):
        """Return a context manager that checks out a pooled connection
        and yields a cursor. See database._PooledCursor."""
        return _PooledCursor(self._pool)

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
                operation_id = cursor.fetchone()[0]
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
        if row:
            return dict(zip(_OPERATION_COLUMNS, row))
        return None

    def list_operations(self, limit: int = 50) -> List[dict]:
        """List recent operations, newest first."""
        query = "SELECT * FROM operations ORDER BY created_at DESC LIMIT %s;"
        with self._cursor as cursor:
            cursor.execute(query, (limit,))
            return [
                dict(zip(_OPERATION_COLUMNS, row))
                for row in cursor.fetchall()
            ]

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
        if row:
            return dict(zip(_OPERATION_COLUMNS, row))
        return None

    def start_operation(self, operation_id: int) -> None:
        """Mark an operation running."""
        query = (
            "UPDATE operations SET status = 'running', started_at = NOW() "
            "WHERE id = %s;"
        )
        with self._cursor as cursor:
            cursor.execute(query, (operation_id,))

    def finish_operation(
        self,
        operation_id: int,
        status: str,
        output: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Mark an operation succeeded or failed."""
        query = """
            UPDATE operations
            SET status = %s, output = %s, error = %s, finished_at = NOW()
            WHERE id = %s;
        """
        with self._cursor as cursor:
            cursor.execute(query, (status, output, error, operation_id))

    def sweep_interrupted_operations(self) -> int:
        """Mark any queued/running operation as interrupted.

        Called once at allocator startup: a row still queued/running means
        the allocator process died mid-job last time, so the Terraform
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
