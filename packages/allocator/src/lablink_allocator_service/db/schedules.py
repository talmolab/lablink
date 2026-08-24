"""Persistence for the scheduled_destructions table.

A standalone table: no foreign key to, and no shared columns with, the VM
table. The scheduled *job* clears VM rows (see scheduler.py), but that is
job behavior, not schema coupling — this class touches only its own table.

Shares the connection pool with the other classes in this package (see
db.pool.make_pool) rather than opening a second one, since POOL_MAX_SIZE is
tuned for the allocator's total connection budget.
"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import List, Optional

import psycopg2

from lablink_allocator_service.db.pool import PooledCursor

logger = logging.getLogger(__name__)


def _naive_utc(dt: datetime) -> datetime:
    """Convert a datetime to naive UTC.

    A private copy of the same helper in db/vms.py — six lines is not worth
    a shared-utils module, and the two callers are on opposite sides of a
    deliberate module boundary.
    """
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


class ScheduleDatabase:
    """Persistence for the scheduled_destructions table.

    Args:
        pool: A psycopg2 connection pool, shared with the other db classes.
    """

    def __init__(self, pool):
        self._pool = pool

    @property
    def _cursor(self):
        """Return a context manager that checks out a pooled connection
        and yields a dict-rows cursor (rows keyed by the database's own
        column names). See db.pool.PooledCursor."""
        return PooledCursor(self._pool, dict_rows=True)

    def create_scheduled_destruction(
        self,
        schedule_name: str,
        destruction_time: datetime,
        recurrence_rule: str = None,
        created_by: str = None,
        notification_enabled: bool = True,
        notification_hours_before: int = 1,
    ) -> int:
        """Create a scheduled destruction entry and return its ID.

        Raises:
            ValueError: If a schedule with the same name already exists
            RuntimeError: If database operation fails
        """
        query = """
            INSERT INTO scheduled_destructions
            (schedule_name, destruction_time, recurrence_rule, created_by,
            notification_enabled, notification_hours_before, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'scheduled')
            RETURNING id;
        """
        with self._cursor as cursor:
            try:
                cursor.execute(
                    query,
                    (
                        schedule_name,
                        _naive_utc(destruction_time),
                        recurrence_rule,
                        created_by,
                        notification_enabled,
                        notification_hours_before,
                    ),
                )
                destruction_id = cursor.fetchone()["id"]
                logger.info(
                    f"Created scheduled destruction "
                    f"'{schedule_name}' "
                    f"(ID: {destruction_id})"
                )
                return destruction_id

            except psycopg2.IntegrityError as e:
                if (
                    'schedule_name' in str(e)
                    or 'unique constraint' in str(e).lower()
                ):
                    error_msg = (
                        f"Schedule '{schedule_name}' already exists"
                    )
                    logger.warning(error_msg)
                    raise ValueError(error_msg) from e
                else:
                    logger.error(
                        f"Database integrity error "
                        f"creating schedule: {e}"
                    )
                    raise RuntimeError(
                        f"Database integrity error: {e}"
                    ) from e

            except Exception as e:
                logger.error(
                    f"Failed to create scheduled destruction "
                    f"'{schedule_name}': {e}"
                )
                raise RuntimeError(
                    f"Failed to create scheduled destruction: {e}"
                ) from e

    def get_scheduled_destruction(self, schedule_id: int) -> Optional[dict]:
        """Get scheduled destruction by ID."""
        query = "SELECT * FROM scheduled_destructions WHERE id = %s;"
        with self._cursor as cursor:
            cursor.execute(query, (schedule_id,))
            row = cursor.fetchone()
        return dict(row) if row else None

    def get_all_scheduled_destructions(
        self, status: Optional[str] = None
    ) -> List[dict]:
        """Get all scheduled destructions, optionally filtered by status."""
        with self._cursor as cursor:
            if status:
                query = (
                    "SELECT * FROM scheduled_destructions "
                    "WHERE status = %s "
                    "ORDER BY destruction_time;"
                )
                cursor.execute(query, (status,))
            else:
                query = (
                    "SELECT * FROM scheduled_destructions "
                    "ORDER BY destruction_time;"
                )
                cursor.execute(query)

            return [dict(row) for row in cursor.fetchall()]

    def update_scheduled_destruction_status(
        self,
        schedule_id: int,
        status: str,
        execution_result: Optional[str] = None,
    ) -> None:
        """Update destruction execution status."""
        query = """
            UPDATE scheduled_destructions
            SET status = %s,
                execution_count = execution_count + 1,
                last_execution_time = NOW(),
                last_execution_result = %s
            WHERE id = %s;
        """
        with self._cursor as cursor:
            cursor.execute(
                query, (status, execution_result, schedule_id)
            )

    def cancel_scheduled_destruction(self, schedule_id: int) -> None:
        """Cancel a scheduled destruction."""
        query = (
            "UPDATE scheduled_destructions "
            "SET status = 'cancelled' WHERE id = %s;"
        )
        with self._cursor as cursor:
            cursor.execute(query, (schedule_id,))
