"""Filesystem sampler.

Polls the watch dir for the newest `.slp` (HDF5) and the newest
`training_log.csv` under `models/`. Returns numeric progress signals
only — no filenames, no paths, no file contents leave this module.

A partially-written `.slp` may raise on open; we swallow and return
None for that field, letting the next tick try again.
"""

import csv
import logging
from pathlib import Path

import h5py

logger = logging.getLogger(__name__)

FRAMES_DATASET = "frames"  # SLEAP project HDF5 layout

# training_log.csv column names have changed across SLEAP versions.
# Walk this list in order; first non-null finite float wins.
#   - "val/loss"   : SLEAP-NN trainer (sleap_nn/training/model_trainer.py)
#   - "train/loss" : SLEAP-NN fallback when validation didn't log
#   - "val_loss"   : SLEAP-NN CSVLoggerCallback default if trainer override skipped
#   - "train_loss" : same, train-side
#   - "loss"       : legacy SLEAP (pre-NN)
LOSS_COLUMN_CANDIDATES = (
    "val/loss",
    "train/loss",
    "val_loss",
    "train_loss",
    "loss",
)


def _latest(paths):
    paths = list(paths)
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_mtime)


def count_labeled_frames(slp: Path) -> int | None:
    try:
        with h5py.File(slp, "r") as f:
            ds = f.get(FRAMES_DATASET)
            if ds is None:
                return None
            return int(ds.shape[0])
    except (OSError, KeyError, ValueError) as e:
        logger.debug("h5py read of %s failed: %s", slp, e)
        return None


def _pick_loss(row: dict) -> float | None:
    """Return the first parseable, finite loss from LOSS_COLUMN_CANDIDATES."""
    for col in LOSS_COLUMN_CANDIDATES:
        raw = row.get(col)
        if raw is None or raw == "":
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            continue
        if v != v:  # NaN guard
            continue
        return v
    return None


def parse_training_log(log: Path) -> tuple[int | None, float | None]:
    try:
        with log.open() as f:
            rows = list(csv.DictReader(f))
    except OSError as e:
        logger.debug("training_log read failed: %s", e)
        return None, None
    if not rows:
        return None, None
    last = rows[-1]
    try:
        epoch = int(float(last.get("epoch", "0")))
    except (TypeError, ValueError):
        return None, None
    return epoch, _pick_loss(last)


def sample(watch_dir: str) -> tuple[int | None, int | None, float | None]:
    root = Path(watch_dir)
    if not root.exists():
        return None, None, None
    slp = _latest(root.glob("*.slp"))
    frames = count_labeled_frames(slp) if slp is not None else None

    log = _latest(root.glob("models/**/training_log.csv"))
    epoch, loss = (None, None)
    if log is not None:
        epoch, loss = parse_training_log(log)

    return frames, epoch, loss
