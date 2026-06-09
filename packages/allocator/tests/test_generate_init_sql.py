"""Tests for generate_init_sql — schema shape and absence of CRD residue."""

from lablink_allocator_service.generate_init_sql import build_init_sql


def test_build_init_sql_returns_string():
    sql = build_init_sql()
    assert isinstance(sql, str)
    assert "CREATE TABLE" in sql


def test_per_session_columns_present():
    sql = build_init_sql()
    for col in ("SessionId", "BrowserToken", "VncPassword",
                "Upstream", "SessionStartedAt"):
        assert col in sql, f"missing column {col}"


def test_partial_unique_indexes_present():
    sql = build_init_sql()
    assert "BrowserToken IS NOT NULL" in sql
    assert "SessionId IS NOT NULL" in sql


def test_settings_table_present():
    sql = build_init_sql()
    assert "CREATE TABLE IF NOT EXISTS settings" in sql
    assert "key TEXT PRIMARY KEY" in sql


def test_crd_columns_absent():
    sql = build_init_sql()
    for symbol in ("CrdCommand", "Pin VARCHAR", "crd_active"):
        assert symbol not in sql, f"unexpected CRD residue: {symbol}"


def test_crd_trigger_absent():
    sql = build_init_sql()
    assert "notify_crd_command_update" not in sql
    assert "trigger_crd_command_insert_or_update" not in sql


def test_phase2_columns_present():
    sql = build_init_sql()
    for col in (
        "machine_identity", "provider", "endpoint_url",
        "provider_metadata", "client_secret_hash",
        "gpu_present", "gpu_model", "last_release_time",
    ):
        assert col in sql, f"missing column {col}"
    assert "provider_metadata  JSONB NOT NULL DEFAULT '{}'" in sql
    assert "provider           TEXT NOT NULL DEFAULT 'aws'" in sql


def test_phase2_indexes_present():
    sql = build_init_sql()
    assert "_machine_identity_idx" in sql
    assert "machine_identity IS NOT NULL" in sql
    assert "_provider_idx" in sql
    assert "_assignable_idx" in sql
    assert "useremail IS NULL AND status = 'running'" in sql


def test_d1_render_columns_present():
    sql = build_init_sql()
    assert "browser_ws_url     TEXT" in sql
    assert "browser_credential TEXT" in sql


def test_vms_table_has_session_metrics_columns():
    """Tier 1 monitoring: session-metrics columns must be present and nullable."""
    from lablink_allocator_service.generate_init_sql import build_init_sql

    sql = build_init_sql()

    expected_columns = [
        "SessionMetricsStartedAt",
        "SessionMetricsSealedAt",
        "SessionMetricsLastReportedAt",
        "SecondsInSubjectSoftware",
        "SecondsInTerminal",
        "SecondsInBrowser",
        "SecondsInOther",
        "GpuActiveSeconds",
        "GpuUtilPeak",
        "VramUsedPeakMb",
        "SecondsToFirstSleapLabel",
        "SecondsToFirstSleapTrain",
        "SecondsToFirstSleapTrack",
        "MaxLabeledFrames",
        "TrainingEpochsCompleted",
        "TrainingFinalLoss",
        "SessionMetricsRaw",
    ]
    for col in expected_columns:
        assert col in sql, f"missing column {col}"

    # None of the new columns should be declared NOT NULL.
    for col in expected_columns:
        assert f"{col} NOT NULL" not in sql, f"{col} must be nullable"
