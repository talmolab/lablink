"""Filesystem sampler — .slp frame count + training_log.csv parse."""

import csv
import os
import time
from unittest.mock import MagicMock, patch

import pytest

from lablink_client_service.monitoring.samplers import filesystem


def test_count_labeled_frames_reads_h5py(tmp_path):
    slp = tmp_path / "labels.slp"
    slp.write_bytes(b"fake")
    fake_h5 = MagicMock()
    fake_h5.__enter__.return_value = {"frames": MagicMock(shape=(480,))}
    fake_h5.__exit__.return_value = False
    with patch(
        "lablink_client_service.monitoring.samplers.filesystem.h5py.File",
        return_value=fake_h5,
    ):
        assert filesystem.count_labeled_frames(slp) == 480


def test_count_labeled_frames_returns_none_on_h5py_error(tmp_path):
    slp = tmp_path / "labels.slp"
    slp.write_bytes(b"fake")
    with patch(
        "lablink_client_service.monitoring.samplers.filesystem.h5py.File",
        side_effect=OSError("bad file"),
    ):
        assert filesystem.count_labeled_frames(slp) is None


def test_parse_training_log_returns_last_epoch_and_loss(tmp_path):
    log = tmp_path / "training_log.csv"
    with log.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "loss"])
        w.writerow(["1", "0.10"])
        w.writerow(["2", "0.05"])
        w.writerow(["3", "0.02"])
    epoch, loss = filesystem.parse_training_log(log)
    assert epoch == 3
    assert loss == pytest.approx(0.02)


def test_parse_training_log_returns_none_for_empty(tmp_path):
    log = tmp_path / "training_log.csv"
    log.write_text("epoch,loss\n")
    assert filesystem.parse_training_log(log) == (None, None)


def test_sample_finds_latest_slp_and_latest_log(tmp_path):
    a = tmp_path / "older.slp"
    b = tmp_path / "newer.slp"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    os.utime(a, (time.time() - 100, time.time() - 100))

    log_dir = tmp_path / "models" / "20260605-1"
    log_dir.mkdir(parents=True)
    log = log_dir / "training_log.csv"
    with log.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "loss"])
        w.writerow(["10", "0.3"])

    fake_h5 = MagicMock()
    fake_h5.__enter__.return_value = {"frames": MagicMock(shape=(99,))}
    fake_h5.__exit__.return_value = False
    with patch(
        "lablink_client_service.monitoring.samplers.filesystem.h5py.File",
        return_value=fake_h5,
    ):
        frames, epochs, loss = filesystem.sample(watch_dir=str(tmp_path))
    assert frames == 99
    assert epochs == 10
    assert loss == pytest.approx(0.3)


def test_sample_returns_none_when_no_files(tmp_path):
    assert filesystem.sample(watch_dir=str(tmp_path)) == (None, None, None)
