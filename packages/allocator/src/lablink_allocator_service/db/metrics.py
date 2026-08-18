"""Persistence for the Tier-1 session-metrics columns.

A column-family split, not a table split: the SessionMetrics* / Seconds* /
Gpu* columns live on the VM table itself, which is why this class needs
table_name where OperationsDatabase needs only a pool. Nothing outside this
module reads or writes those columns, with one soft exception —
VmDatabase.get_all_vms_for_export does SELECT * via get_column_names()
and therefore returns them too. That is a schema-shape dependency, not a code
one.
"""
from __future__ import annotations

from psycopg2.extras import Json

from lablink_allocator_service.db.pool import PooledCursor


def _median(values: list):
    """Median of a list, ignoring None. Returns None when the list is empty.

    Uses floor division for the even-length case because every column
    fed in here is INTEGER in the schema; `960` reads more cleanly in
    the rendered admin tile than `960.0`. If a future caller passes a
    DOUBLE PRECISION column, switch this site to true division.
    """
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    n = len(values)
    mid = n // 2
    if n % 2 == 1:
        return values[mid]
    return (values[mid - 1] + values[mid]) // 2


def _build_summary(rows: list) -> dict:
    """Build the session-metrics cohort summary from an iterable of dict
    rows (keyed as aliased in get_session_metrics_summary's SELECT).

    A NULL column arrives as an explicit None value, and a missing key
    would mean the SELECT and this function disagree — `[...]` access
    below raises KeyError rather than silently medianizing to None.
    """
    total = len(rows)
    started = sum(1 for r in rows if r["session_metrics_started_at"] is not None)
    labeled = sum(1 for r in rows if r["seconds_to_first_sleap_label"] is not None)
    trained = sum(1 for r in rows if r["seconds_to_first_sleap_train"] is not None)
    tracked = sum(1 for r in rows if r["seconds_to_first_sleap_track"] is not None)
    secs_in_subject = [r["seconds_in_subject_software"] for r in rows]
    first_train = [r["seconds_to_first_sleap_train"] for r in rows]
    frames = [r["max_labeled_frames"] for r in rows]
    epochs = [r["training_epochs_completed"] for r in rows]
    pct_train = (trained / total * 100.0) if total else 0.0
    return {
        "total_vms": total,
        "funnel": {
            "started": started,
            "labeled": labeled,
            "trained": trained,
            "tracked": tracked,
        },
        "pct_reached_training": pct_train,
        "median_seconds_in_subject_software": _median(secs_in_subject),
        "median_seconds_to_first_train": _median(first_train),
        "median_labeled_frames": _median(frames),
        "median_epochs_completed": _median(epochs),
    }


class MetricsDatabase:
    """Persistence for session-metrics columns on the VM table.

    Args:
        pool: A psycopg2 connection pool, shared with the other db classes.
        table_name: The VM table name (VM_TABLE_NAME in production).
    """

    def __init__(self, pool, table_name: str):
        self._pool = pool
        self.table_name = table_name

    @property
    def _cursor(self):
        """Return a context manager that checks out a pooled connection
        and yields a dict-rows cursor (rows keyed by the database's own
        column names). See db.pool.PooledCursor."""
        return PooledCursor(self._pool, dict_rows=True)

    def update_session_metrics(self, hostname: str, payload: dict) -> None:
        """Last-write-wins UPDATE of session-metrics columns.

        Atomic with respect to seal: the sealed-row check is folded into
        the UPDATE's WHERE clause, so a concurrent ``bulk_seal_session_metrics``
        cannot land between a separate SELECT and a separate UPDATE.
        When the UPDATE affects zero rows, a follow-up existence SELECT
        classifies the failure as ``LookupError`` (no such row) or
        ``ValueError`` (row exists but is sealed).

        Raises:
            LookupError: if hostname unknown.
            ValueError: if the row is already sealed.
        """
        counters = payload.get("counters", {})
        with self._cursor as cursor:
            cursor.execute(
                f"""
                UPDATE {self.table_name} SET
                  SessionMetricsStartedAt      = COALESCE(SessionMetricsStartedAt, %s),
                  SessionMetricsLastReportedAt = NOW(),
                  SecondsInSubjectSoftware     = %s,
                  SecondsInTerminal            = %s,
                  SecondsInBrowser             = %s,
                  SecondsInOther               = %s,
                  GpuActiveSeconds             = %s,
                  GpuUtilPeak                  = %s,
                  VramUsedPeakMb               = %s,
                  SecondsToFirstSleapLabel     = %s,
                  SecondsToFirstSleapTrain     = %s,
                  SecondsToFirstSleapTrack     = %s,
                  MaxLabeledFrames             = %s,
                  TrainingEpochsCompleted      = %s,
                  TrainingFinalLoss            = %s,
                  SessionMetricsRaw            = %s
                WHERE HostName = %s AND SessionMetricsSealedAt IS NULL
                """,
                (
                    payload.get("session_started_at"),
                    counters.get("seconds_in_subject_software"),
                    counters.get("seconds_in_terminal"),
                    counters.get("seconds_in_browser"),
                    counters.get("seconds_in_other"),
                    counters.get("gpu_active_seconds"),
                    counters.get("gpu_util_peak"),
                    counters.get("vram_used_peak_mb"),
                    counters.get("seconds_to_first_sleap_label"),
                    counters.get("seconds_to_first_sleap_train"),
                    counters.get("seconds_to_first_sleap_track"),
                    counters.get("max_labeled_frames"),
                    counters.get("training_epochs_completed"),
                    counters.get("training_final_loss"),
                    Json(counters),
                    hostname,
                ),
            )
            if cursor.rowcount >= 1:
                return

            # UPDATE matched zero rows — classify so the route can return
            # 404 vs 409. HostName is PRIMARY KEY on vms, so this SELECT
            # can return at most one row.
            cursor.execute(
                f"SELECT 1 FROM {self.table_name} WHERE HostName = %s",
                (hostname,),
            )
            if cursor.fetchone() is None:
                raise LookupError(f"VM {hostname} not found")
            raise ValueError(f"VM {hostname} session is sealed")

    def bulk_seal_session_metrics(self) -> int:
        """Seal every unsealed VM (called from the destroy paths).

        Returns:
            int: number of rows sealed.
        """
        with self._cursor as cursor:
            cursor.execute(
                f"UPDATE {self.table_name} SET SessionMetricsSealedAt = NOW() "
                "WHERE SessionMetricsSealedAt IS NULL"
            )
            return cursor.rowcount or 0

    def get_session_metrics_summary(self) -> dict:
        """Aggregate the cohort summary for the admin page.

        The AS aliases below ARE the row keys `_build_summary` reads —
        the dict-rows cursor keys each row by them (Postgres folds the
        unquoted CamelCase column names to bare lowercase, hence the
        explicit snake_case aliases).
        """
        with self._cursor as cursor:
            cursor.execute(
                f"""
                SELECT HostName                 AS host_name,
                       SessionMetricsStartedAt  AS session_metrics_started_at,
                       SecondsToFirstSleapLabel AS seconds_to_first_sleap_label,
                       SecondsToFirstSleapTrain AS seconds_to_first_sleap_train,
                       SecondsToFirstSleapTrack AS seconds_to_first_sleap_track,
                       SecondsInSubjectSoftware AS seconds_in_subject_software,
                       GpuActiveSeconds         AS gpu_active_seconds,
                       MaxLabeledFrames         AS max_labeled_frames,
                       TrainingEpochsCompleted  AS training_epochs_completed
                FROM {self.table_name}
                """
            )
            rows = cursor.fetchall()
        return _build_summary(rows)
