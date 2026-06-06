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
        loss = float(last.get("loss", "nan"))
        loss = None if loss != loss else loss  # NaN guard
    except (TypeError, ValueError):
        return None, None
    return epoch, loss


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
