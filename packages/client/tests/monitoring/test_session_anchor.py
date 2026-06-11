"""Tests for the cross-process session-anchor mechanism.

Covers the file contract (session_anchor module) and the monitoring
loop's reset hook (_maybe_reanchor) in isolation from the full main()
loop — the entry-point tests already exercise that.
"""

from datetime import datetime, timedelta, timezone

import pytest

from lablink_client_service import session_anchor
from lablink_client_service.monitoring import __main__ as entry
from lablink_client_service.monitoring.aggregator import new_counters


@pytest.fixture
def anchor_path(tmp_path, monkeypatch):
    path = tmp_path / "session-anchor"
    monkeypatch.setenv("LABLINK_SESSION_ANCHOR_PATH", str(path))
    return path


def test_write_then_read_anchor_round_trip(anchor_path):
    ts = datetime(2026, 6, 11, 15, 21, 26, 252786, tzinfo=timezone.utc)
    session_anchor.write_anchor(ts)
    assert session_anchor.read_anchor() == ts


def test_read_anchor_returns_none_when_file_missing(anchor_path):
    assert not anchor_path.exists()
    assert session_anchor.read_anchor() is None


def test_read_anchor_returns_none_when_file_unparseable(anchor_path):
    anchor_path.write_text("not a timestamp")
    assert session_anchor.read_anchor() is None


def test_write_anchor_is_atomic_no_temp_left_behind(anchor_path, tmp_path):
    ts = datetime(2026, 6, 11, 15, 0, 0, tzinfo=timezone.utc)
    session_anchor.write_anchor(ts)
    # Only the final file should remain; the .tmp sibling must have been renamed.
    assert anchor_path.exists()
    assert not (tmp_path / "session-anchor.tmp").exists()


def test_maybe_reanchor_returns_same_counters_when_no_anchor(anchor_path):
    """No file on disk → no reset; current counters keep advancing."""
    boot = datetime(2026, 6, 11, 9, 0, 0, tzinfo=timezone.utc)
    c = new_counters(session_started_at=boot)
    c.seconds_in_subject_software = 42
    result = entry._maybe_reanchor(c)
    assert result is c  # same object, unchanged
    assert result.seconds_in_subject_software == 42


def test_maybe_reanchor_returns_same_counters_when_anchor_unchanged(anchor_path):
    """File matches the current anchor → no reset, accumulators preserved."""
    ts = datetime(2026, 6, 11, 15, 21, 26, tzinfo=timezone.utc)
    session_anchor.write_anchor(ts)
    c = new_counters(session_started_at=ts)
    c.seconds_in_subject_software = 100
    result = entry._maybe_reanchor(c)
    assert result is c
    assert result.seconds_in_subject_software == 100


def test_maybe_reanchor_resets_when_anchor_is_newer(anchor_path):
    """Agent wrote a new assignment timestamp → counters reset and re-anchor.

    Full reset: every accumulator field zeroes out so the resulting row
    describes the new user's session only.
    """
    boot_ts = datetime(2026, 6, 11, 9, 0, 0, tzinfo=timezone.utc)
    assignment_ts = boot_ts + timedelta(hours=6, minutes=21, seconds=26)
    session_anchor.write_anchor(assignment_ts)

    c = new_counters(session_started_at=boot_ts)
    c.seconds_in_subject_software = 14396
    c.seconds_in_terminal = 648
    c.gpu_active_seconds = 1500
    c.seconds_to_first_sleap_train = 25138

    result = entry._maybe_reanchor(c)

    assert result is not c
    assert result.session_started_at == assignment_ts
    assert result.seconds_in_subject_software == 0
    assert result.seconds_in_terminal == 0
    assert result.gpu_active_seconds == 0
    assert result.seconds_to_first_sleap_train is None
    assert result.sample_count == 0


def test_maybe_reanchor_handles_reclaim_second_assignment(anchor_path):
    """A second /api/session/start (re-claim) writes a newer anchor;
    the loop must reset again, dropping the first user's metrics."""
    first_assignment = datetime(2026, 6, 11, 15, 0, 0, tzinfo=timezone.utc)
    second_assignment = datetime(2026, 6, 11, 17, 30, 0, tzinfo=timezone.utc)

    session_anchor.write_anchor(first_assignment)
    boot = datetime(2026, 6, 11, 9, 0, 0, tzinfo=timezone.utc)
    c = new_counters(session_started_at=boot)
    c = entry._maybe_reanchor(c)
    assert c.session_started_at == first_assignment
    c.seconds_in_subject_software = 2000  # first user accumulated some time

    session_anchor.write_anchor(second_assignment)
    c = entry._maybe_reanchor(c)
    assert c.session_started_at == second_assignment
    assert c.seconds_in_subject_software == 0
