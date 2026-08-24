"""Database helpers for the Tier 1 monitoring feature."""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest


@pytest.fixture
def fake_db():
    """Return a MetricsDatabase instance with a mocked cursor."""
    from lablink_allocator_service.db.metrics import MetricsDatabase

    db = MetricsDatabase.__new__(MetricsDatabase)
    db.table_name = "vms"
    db._cursor_mock = MagicMock()
    cursor_ctx = MagicMock(
        __enter__=MagicMock(return_value=db._cursor_mock),
        __exit__=MagicMock(return_value=False),
    )
    # _cursor is a property on MetricsDatabase; override it at the class
    # level for the duration of each test.
    patcher = patch.object(
        MetricsDatabase,
        "_cursor",
        new_callable=PropertyMock,
        return_value=cursor_ctx,
    )
    patcher.start()
    yield db
    patcher.stop()


def test_update_session_metrics_writes_columns(fake_db):
    payload = {
        "session_started_at": "2026-06-05T17:00:00Z",
        "counters": {
            "sample_count": 100,
            "seconds_in_subject_software": 200,
            "seconds_in_terminal": 50,
            "seconds_in_browser": 25,
            "seconds_in_other": 125,
            "gpu_active_seconds": 80,
            "gpu_util_peak": 95,
            "vram_used_peak_mb": 14000,
            "seconds_to_first_sleap_label": 300,
            "seconds_to_first_sleap_train": 1080,
            "seconds_to_first_sleap_track": None,
            "max_labeled_frames": 480,
            "training_epochs_completed": 35,
            "training_final_loss": 0.0142,
        },
    }
    # UPDATE matched the row (not sealed) — happy path.
    fake_db._cursor_mock.rowcount = 1
    fake_db.update_session_metrics("vm-1", payload)
    sql_calls = [c.args[0] for c in fake_db._cursor_mock.execute.call_args_list]
    # UPDATE fired with the sealed-row guard folded into WHERE.
    update_sql = next(s for s in sql_calls if "UPDATE" in s.upper())
    assert "SecondsInSubjectSoftware" in update_sql
    assert "SessionMetricsSealedAt IS NULL" in update_sql
    # No follow-up existence SELECT needed on the happy path.
    assert fake_db._cursor_mock.execute.call_count == 1


def test_update_session_metrics_refuses_when_sealed(fake_db):
    """UPDATE matches zero rows AND the row exists -> sealed."""
    fake_db._cursor_mock.rowcount = 0
    fake_db._cursor_mock.fetchone.return_value = (1,)  # row exists
    payload = {"session_started_at": "x", "counters": {}}
    with pytest.raises(ValueError, match="sealed"):
        fake_db.update_session_metrics("vm-1", payload)


def test_update_session_metrics_lookup_error_when_host_unknown(fake_db):
    """UPDATE matches zero rows AND no row exists -> LookupError."""
    fake_db._cursor_mock.rowcount = 0
    fake_db._cursor_mock.fetchone.return_value = None
    payload = {"session_started_at": "x", "counters": {}}
    with pytest.raises(LookupError, match="not found"):
        fake_db.update_session_metrics("vm-missing", payload)


def test_bulk_seal_session_metrics_targets_all_unsealed(fake_db):
    fake_db.bulk_seal_session_metrics()
    sql = fake_db._cursor_mock.execute.call_args.args[0]
    assert "SessionMetricsSealedAt IS NULL" in sql


def _summary_row(host, started, label, train, track, subject, gpu, frames, epochs):
    """A dict row keyed as the summary SELECT aliases its columns."""
    return {
        "host_name": host,
        "session_metrics_started_at": started,
        "seconds_to_first_sleap_label": label,
        "seconds_to_first_sleap_train": train,
        "seconds_to_first_sleap_track": track,
        "seconds_in_subject_software": subject,
        "gpu_active_seconds": gpu,
        "max_labeled_frames": frames,
        "training_epochs_completed": epochs,
    }


def test_get_session_metrics_summary_returns_funnel_counts(fake_db):
    fake_db._cursor_mock.fetchall.return_value = [
        _summary_row("vm-1", "2026-06-05T17:00:00Z", 300, 1080, 3120, 4820, 1640, 480, 35),
        _summary_row("vm-2", "2026-06-05T17:01:00Z", 540, None, None, 820, 0, 12, 0),
        _summary_row("vm-3", "2026-06-05T17:02:00Z", 280, 720, None, 3200, 1100, 240, 18),
    ]
    summary = fake_db.get_session_metrics_summary()
    assert summary["total_vms"] == 3
    assert summary["funnel"]["started"] == 3
    assert summary["funnel"]["labeled"] == 3
    assert summary["funnel"]["trained"] == 2
    assert summary["funnel"]["tracked"] == 1
    assert summary["pct_reached_training"] == pytest.approx(2 / 3 * 100, abs=0.1)
    # Medians over non-null values
    assert summary["median_seconds_in_subject_software"] == 3200
    assert summary["median_seconds_to_first_train"] == 900  # median of [720, 1080]
    assert summary["median_labeled_frames"] == 240          # median of [12, 240, 480]
    assert summary["median_epochs_completed"] == 18         # median of [0, 18, 35]


def test_summary_raises_loudly_on_missing_key(fake_db):
    """Drift between the SELECT's aliases and _build_summary's keys must
    be a KeyError at the access, not a silently-None median (the old
    zip-based rows degraded short rows to plausible-but-wrong output)."""
    row = _summary_row("vm-1", "2026-06-05T17:00:00Z", 300, 1080, 3120, 4820, 1640, 480, 35)
    del row["max_labeled_frames"]
    fake_db._cursor_mock.fetchall.return_value = [row]
    with pytest.raises(KeyError, match="max_labeled_frames"):
        fake_db.get_session_metrics_summary()


def test_update_session_metrics_returns_session_started_at(fake_db):
    """The UPDATE RETURNs the row's authoritative SessionStartedAt so the
    route can echo it back for client anchor healing."""
    from datetime import datetime, timezone

    started = datetime(2026, 6, 11, 15, 21, 13, tzinfo=timezone.utc)
    fake_db._cursor_mock.rowcount = 1
    fake_db._cursor_mock.fetchone.return_value = {"session_started_at": started}
    result = fake_db.update_session_metrics(
        "vm-1", {"session_started_at": None, "counters": {}}
    )
    assert result == started
    update_sql = fake_db._cursor_mock.execute.call_args_list[0].args[0]
    assert "RETURNING SessionStartedAt AS session_started_at" in update_sql
