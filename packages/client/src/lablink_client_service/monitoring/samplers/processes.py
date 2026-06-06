"""Process sampler.

Walks /proc/*/comm and returns the set of allowlisted process names
currently present. Skips numeric-only entry directories silently when
unreadable (process exited mid-scan).
"""

import logging
import os
from typing import Iterable, Set

logger = logging.getLogger(__name__)


def sample(allowlist: Iterable[str], proc_root: str = "/proc") -> Set[str]:
    wanted = set(allowlist)
    seen: Set[str] = set()
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return seen

    for name in entries:
        if not name.isdigit():
            continue
        comm_path = os.path.join(proc_root, name, "comm")
        try:
            with open(comm_path) as f:
                comm = f.read().strip()
        except OSError:
            continue
        if comm in wanted:
            seen.add(comm)
        if seen == wanted:
            break
    return seen
