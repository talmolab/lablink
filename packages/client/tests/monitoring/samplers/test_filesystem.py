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


def test_parse_training_log_legacy_loss_column(tmp_path):
    """Pre-NN SLEAP wrote a single `loss` column. Still supported."""
    log = tmp_path / "training_log.csv"
    with log.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "loss"])
        w.writerow(["1", "0.10"])
        w.writerow(["3", "0.02"])
    epoch, loss = filesystem.parse_training_log(log)
    assert epoch == 3
    assert loss == pytest.approx(0.02)


def test_parse_training_log_sleap_nn_slash_columns(tmp_path):
    """SLEAP-NN trainer writes `train/loss` and `val/loss`. `val/loss`
    wins because validation is the more meaningful generalization signal.
    """
    log = tmp_path / "training_log.csv"
    with log.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "train/loss", "val/loss", "learning_rate"])
        w.writerow(["1", "0.50", "0.55", "1e-3"])
        w.writerow(["7", "0.04", "0.07", "1e-4"])
    epoch, loss = filesystem.parse_training_log(log)
    assert epoch == 7
    assert loss == pytest.approx(0.07)  # val/loss preferred over train/loss


def test_parse_training_log_falls_back_to_train_loss(tmp_path):
    """If only `train/loss` is logged (no validation), use it."""
    log = tmp_path / "training_log.csv"
    with log.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "train/loss", "learning_rate"])
        w.writerow(["4", "0.12", "1e-3"])
    epoch, loss = filesystem.parse_training_log(log)
    assert epoch == 4
    assert loss == pytest.approx(0.12)


def test_parse_training_log_underscore_keys(tmp_path):
    """SLEAP-NN CSVLoggerCallback default keys use underscores."""
    log = tmp_path / "training_log.csv"
    with log.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "train_loss", "val_loss", "learning_rate"])
        w.writerow(["5", "0.20", "0.30", "1e-3"])
    epoch, loss = filesystem.parse_training_log(log)
    assert epoch == 5
    assert loss == pytest.approx(0.30)


def test_parse_training_log_skips_nan_and_empty(tmp_path):
    """NaN / empty values in the preferred column fall through to the next."""
    log = tmp_path / "training_log.csv"
    with log.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "val/loss", "train/loss"])
        w.writerow(["2", "nan", "0.40"])  # val/loss NaN -> train/loss wins
    epoch, loss = filesystem.parse_training_log(log)
    assert epoch == 2
    assert loss == pytest.approx(0.40)


def test_parse_training_log_returns_none_for_empty(tmp_path):
    log = tmp_path / "training_log.csv"
    log.write_text("epoch,loss\n")
    assert filesystem.parse_training_log(log) == (None, None)


def test_parse_training_log_epoch_known_loss_unknown(tmp_path):
    """No recognised loss column → epoch survives, loss is None."""
    log = tmp_path / "training_log.csv"
    with log.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["epoch", "some_other_metric"])
        w.writerow(["3", "42"])
    epoch, loss = filesystem.parse_training_log(log)
    assert epoch == 3
    assert loss is None


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
