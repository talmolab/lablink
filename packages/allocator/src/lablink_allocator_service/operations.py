"""Background worker for on-demand Terraform apply/destroy operations.

Runs each operation on its own daemon thread, off the Flask request
thread, so a slow `terraform apply`/`destroy` doesn't hold an HTTP
connection open long enough to hit Cloudflare's edge timeout.
"""
from __future__ import annotations

import logging
from threading import Thread
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from lablink_allocator_service.operations_db import OperationsDatabase

logger = logging.getLogger(__name__)


class OperationsWorker:
    """Submits apply/destroy jobs to run on a background thread.

    Args:
        database: OperationsDatabase instance for operation-status persistence.
    """

    def __init__(self, database: "OperationsDatabase"):
        self.database = database

    def start(self) -> None:
        """Mark any operation left queued/running from a prior process as
        interrupted. Call once at allocator startup, before any new
        operation can be submitted, so a crash/restart mid-job is surfaced
        instead of hanging forever or being silently forgotten."""
        count = self.database.sweep_interrupted_operations()
        if count:
            logger.warning(
                "Marked %d operation(s) interrupted "
                "(allocator restarted mid-job)",
                count,
            )

    def submit(
        self,
        op_type: str,
        fn: Callable[[], str],
        params: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> int:
        """Queue a new operation and run it on a background thread.

        Returns immediately after the operation row is created — does not
        wait for `fn` to complete.

        Raises:
            OperationInProgress: propagated from database.create_operation
                if another operation is already queued/running.
        """
        operation_id = self.database.create_operation(
            op_type=op_type, params=params, created_by=created_by
        )
        Thread(
            target=self._run, args=(operation_id, fn), daemon=True
        ).start()
        return operation_id

    def _run(self, operation_id: int, fn: Callable[[], str]) -> None:
        try:
            self.database.start_operation(operation_id)
            output = fn()
        except Exception as e:
            logger.error(
                "Operation #%d failed: %s", operation_id, e, exc_info=True
            )
            self.database.finish_operation(
                operation_id, status="failed", error=str(e)
            )
            return
        self.database.finish_operation(
            operation_id, status="succeeded", output=output
        )
