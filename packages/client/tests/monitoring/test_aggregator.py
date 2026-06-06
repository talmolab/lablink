"""Counter math for the Tier 1 monitoring aggregator."""

from datetime import datetime, timezone

import pytest

from lablink_client_service.monitoring.aggregator import (
    Sample,
    SessionCounters,
    apply_sample,
    new_counters,
)


def test_session_counters_type_importable():
    assert SessionCounters.__name__ == "SessionCounters"


@pytest.fixture
def t0():
    return datetime(2026, 6, 5, 17, 0, 0, tzinfo=timezone.utc)


def test_new_counters_zero(t0):
    c = new_counters(session_started_at=t0)
    assert c.session_started_at == t0
    assert c.sample_count == 0
    assert c.seconds_in_subject_software == 0
    assert c.gpu_util_peak == 0
    assert c.seconds_to_first_sleap_train is None


def test_apply_sample_in_subject_increments_only_subject(t0):
    c = new_counters(session_started_at=t0)
    sample = Sample(
        ts=t0,
        sample_interval_seconds=2,
        active_window_bucket="subject",
        gpu_util_pct=0,
        vram_mb=0,
        processes_seen=set(),
        max_labeled_frames=None,
        training_epochs_completed=None,
        training_final_loss=None,
    )
    apply_sample(c, sample)
    assert c.seconds_in_subject_software == 2
    assert c.seconds_in_terminal == 0
    assert c.sample_count == 1


def test_apply_sample_gpu_active_threshold_5pct(t0):
    c = new_counters(session_started_at=t0)
    apply_sample(c, _gpu_sample(t0, util=3, vram=1000))
    apply_sample(c, _gpu_sample(t0, util=6, vram=1500))
    assert c.gpu_active_seconds == 2
    assert c.gpu_util_peak == 6
    assert c.vram_used_peak_mb == 1500


def test_first_sleap_train_stamped_once(t0):
    from datetime import timedelta

    c = new_counters(session_started_at=t0)
    later = t0 + timedelta(seconds=300)
    much_later = t0 + timedelta(seconds=900)
    apply_sample(c, _proc_sample(later, {"sleap-train"}))
    apply_sample(c, _proc_sample(much_later, {"sleap-train"}))
    assert c.seconds_to_first_sleap_train == 300


def test_filesystem_signals_take_max(t0):
    c = new_counters(session_started_at=t0)
    apply_sample(
        c,
        _fs_sample(t0, frames=12, epochs=2, loss=0.5),
    )
    apply_sample(
        c,
        _fs_sample(t0, frames=480, epochs=35, loss=0.014),
    )
    assert c.max_labeled_frames == 480
    assert c.training_epochs_completed == 35
    assert c.training_final_loss == pytest.approx(0.014)


def _gpu_sample(ts, util, vram):
    return Sample(
        ts=ts,
        sample_interval_seconds=1,
        active_window_bucket="other",
        gpu_util_pct=util,
        vram_mb=vram,
        processes_seen=set(),
        max_labeled_frames=None,
        training_epochs_completed=None,
        training_final_loss=None,
    )


def _proc_sample(ts, procs):
    return Sample(
        ts=ts,
        sample_interval_seconds=1,
        active_window_bucket="other",
        gpu_util_pct=0,
        vram_mb=0,
        processes_seen=procs,
        max_labeled_frames=None,
        training_epochs_completed=None,
        training_final_loss=None,
    )


def _fs_sample(ts, frames, epochs, loss):
    return Sample(
        ts=ts,
        sample_interval_seconds=1,
        active_window_bucket="other",
        gpu_util_pct=0,
        vram_mb=0,
        processes_seen=set(),
        max_labeled_frames=frames,
        training_epochs_completed=epochs,
        training_final_loss=loss,
    )
