"""Database helpers for the Tier 1 monitoring feature."""

from unittest.mock import MagicMock, PropertyMock, patch

import pytest


@pytest.fixture
def fake_db():
    """Return a PostgresqlDatabase instance with mocked cursor."""
    from lablink_allocator_service.database import PostgresqlDatabase

    db = PostgresqlDatabase.__new__(PostgresqlDatabase)
    db.table_name = "vms"
    db._cursor_mock = MagicMock()
    cursor_ctx = MagicMock(
        __enter__=MagicMock(return_value=db._cursor_mock),
        __exit__=MagicMock(return_value=False),
    )
    # _cursor is a property on PostgresqlDatabase; override it at the
    # class level for the duration of each test.
    patcher = patch.object(
        PostgresqlDatabase,
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
    fake_db._cursor_mock.fetchone.return_value = (None,)  # not sealed
    fake_db.update_session_metrics("vm-1", payload)
    sql_calls = [c.args[0] for c in fake_db._cursor_mock.execute.call_args_list]
    assert any("SecondsInSubjectSoftware" in s for s in sql_calls)
    assert any("UPDATE" in s.upper() for s in sql_calls)


def test_update_session_metrics_refuses_when_sealed(fake_db):
    fake_db._cursor_mock.fetchone.return_value = ("2026-06-05T18:00:00Z",)
    payload = {"session_started_at": "x", "counters": {}}
    with pytest.raises(ValueError, match="sealed"):
        fake_db.update_session_metrics("vm-1", payload)


def test_seal_session_metrics_sets_sealed_at(fake_db):
    fake_db.seal_session_metrics("vm-1")
    sql = fake_db._cursor_mock.execute.call_args.args[0]
    assert "SessionMetricsSealedAt" in sql
    assert "vm-1" in str(fake_db._cursor_mock.execute.call_args.args[1])


def test_bulk_seal_session_metrics_targets_all_unsealed(fake_db):
    fake_db.bulk_seal_session_metrics()
    sql = fake_db._cursor_mock.execute.call_args.args[0]
    assert "SessionMetricsSealedAt IS NULL" in sql


def test_get_session_metrics_summary_returns_funnel_counts(fake_db):
    fake_db._cursor_mock.fetchall.return_value = [
        ("vm-1", "2026-06-05T17:00:00Z", 300, 1080, 3120, 4820, 1640),
        ("vm-2", "2026-06-05T17:01:00Z", 540, None, None, 820, 0),
        ("vm-3", "2026-06-05T17:02:00Z", 280, 720, None, 3200, 1100),
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
