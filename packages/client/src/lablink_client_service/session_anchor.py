"""Inter-process session-start anchor.

The client container runs two long-lived processes started by start.sh: the
agent (:7070) that receives `POST /api/session/start` from the allocator
when a user is assigned the seat, and the monitoring agent that pushes
session counters to the allocator. The monitoring agent's counters
(`seconds_to_first_sleap_train`, `seconds_in_subject_software`, …) must
be anchored at user-assignment time, not VM boot, so the metrics describe
user behavior rather than infrastructure idle time.

The two processes don't share memory, so the agent writes the assignment
timestamp here and the monitoring loop polls the file each tick. When it
sees a timestamp it hasn't acted on yet, it resets its counters with the
new anchor.

File contents: a single ISO-8601 UTC string (microsecond precision).
Path: $LABLINK_SESSION_ANCHOR_PATH or /tmp/lablink-session-anchor.
"""

import os
from datetime import datetime

DEFAULT_ANCHOR_PATH = "/tmp/lablink-session-anchor"


def get_anchor_path() -> str:
    return os.environ.get("LABLINK_SESSION_ANCHOR_PATH", DEFAULT_ANCHOR_PATH)


def write_anchor(ts: datetime, path: str | None = None) -> None:
    """Atomically write the anchor timestamp.

    Write to a sibling temp file then rename so a concurrent reader never
    sees a half-written line.
    """
    target = path or get_anchor_path()
    tmp = f"{target}.tmp"
    with open(tmp, "w") as f:
        f.write(ts.isoformat())
    os.replace(tmp, target)


def read_anchor(path: str | None = None) -> datetime | None:
    """Return the parsed anchor timestamp, or None if missing/unreadable.

    Any IO or parse error returns None — the caller treats "no anchor" the
    same as "anchor unchanged", so a transient read failure just defers the
    reset to the next tick.
    """
    target = path or get_anchor_path()
    try:
        with open(target) as f:
            raw = f.read().strip()
    except OSError:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
