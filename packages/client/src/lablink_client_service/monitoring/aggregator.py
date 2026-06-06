"""Rolling counters for the Tier 1 monitoring agent.

The aggregator holds in-memory state only. Each sampler produces a Sample
once per tick (default 2 s); `apply_sample` updates the counters with that
sample's effect on the running totals. The counters are serialised to
JSON by the pusher and POSTed to the allocator.

There is no per-sample storage. Crashing the process loses at most the
last `push_interval_seconds` of counter state.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Set

GPU_ACTIVE_UTIL_THRESHOLD = 5

# "subject" stores time spent in the configured tutorial app (SLEAP, DeepLabCut, …).
# The sampler returns this bucket name when the active-window title matches any
# of the patterns in subject_window_patterns.
WINDOW_BUCKETS = ("subject", "terminal", "browser", "other")
SUBJECT_FIELD = "seconds_in_subject_software"  # column name override


@dataclass
class Sample:
    """One tick of input from the four samplers."""

    ts: datetime
    sample_interval_seconds: int
    active_window_bucket: str  # one of WINDOW_BUCKETS
    gpu_util_pct: int
    vram_mb: int
    processes_seen: Set[str]
    max_labeled_frames: int | None
    training_epochs_completed: int | None
    training_final_loss: float | None


@dataclass
class SessionCounters:
    session_started_at: datetime
    sample_count: int = 0

    seconds_in_subject_software: int = 0
    seconds_in_terminal: int = 0
    seconds_in_browser: int = 0
    seconds_in_other: int = 0

    gpu_active_seconds: int = 0
    gpu_util_peak: int = 0
    vram_used_peak_mb: int = 0

    seconds_to_first_sleap_label: int | None = None
    seconds_to_first_sleap_train: int | None = None
    seconds_to_first_sleap_track: int | None = None

    max_labeled_frames: int = 0
    training_epochs_completed: int = 0
    training_final_loss: float | None = None


def new_counters(session_started_at: datetime) -> SessionCounters:
    return SessionCounters(session_started_at=session_started_at)


def apply_sample(c: SessionCounters, s: Sample) -> None:
    c.sample_count += 1

    bucket = (
        s.active_window_bucket if s.active_window_bucket in WINDOW_BUCKETS else "other"
    )
    attr = SUBJECT_FIELD if bucket == "subject" else f"seconds_in_{bucket}"
    setattr(c, attr, getattr(c, attr) + s.sample_interval_seconds)

    if s.gpu_util_pct > GPU_ACTIVE_UTIL_THRESHOLD or s.vram_mb > 0:
        c.gpu_active_seconds += s.sample_interval_seconds
    if s.gpu_util_pct > c.gpu_util_peak:
        c.gpu_util_peak = s.gpu_util_pct
    if s.vram_mb > c.vram_used_peak_mb:
        c.vram_used_peak_mb = s.vram_mb

    elapsed = int((s.ts - c.session_started_at).total_seconds())
    if "sleap-label" in s.processes_seen and c.seconds_to_first_sleap_label is None:
        c.seconds_to_first_sleap_label = elapsed
    if "sleap-train" in s.processes_seen and c.seconds_to_first_sleap_train is None:
        c.seconds_to_first_sleap_train = elapsed
    if "sleap-track" in s.processes_seen and c.seconds_to_first_sleap_track is None:
        c.seconds_to_first_sleap_track = elapsed

    if s.max_labeled_frames is not None and s.max_labeled_frames > c.max_labeled_frames:
        c.max_labeled_frames = s.max_labeled_frames
    if (
        s.training_epochs_completed is not None
        and s.training_epochs_completed > c.training_epochs_completed
    ):
        c.training_epochs_completed = s.training_epochs_completed
    if s.training_final_loss is not None:
        c.training_final_loss = s.training_final_loss
