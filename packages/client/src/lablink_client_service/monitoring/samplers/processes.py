"""Process sampler.

Walks /proc/*/cmdline and returns the set of allowlisted process names
currently present. We read cmdline (not comm) because SLEAP's GUI ships
entry-point shim scripts: their /proc/<pid>/comm reads "python3", but
argv[0] is the real binary path. comm-based matching never fires.

Three SLEAP invocation shapes are recognised, normalised to the
canonical names in the allowlist:

  1. Direct entry-point script — `sleap-label`, `sleap-train`,
     `sleap-track`. Matched on argv[0] basename. Covers the GUI binary
     itself (`sleap-label`) and any hand-run CLI.
  2. `sleap <subcommand>` — e.g. `sleap track …`. The SLEAP GUI uses
     this shape for inference (sleap/gui/learning/runners.py:541).
  3. `<python> -m sleap.cli <subcommand>` — the SLEAP GUI uses this
     shape for training, deliberately (PyTorch Lightning DDP needs
     __main__.__spec__ set, which entry-point scripts don't provide;
     sleap/gui/learning/runners.py:1311). argv[0] is the python
     interpreter.
"""

import logging
import os
from typing import Iterable, List, Set

logger = logging.getLogger(__name__)


def _read_cmdline(path: str) -> List[str] | None:
    """Read /proc/<pid>/cmdline as a list of argv strings.

    Returns None if the file can't be read (process exited mid-scan) or
    is empty (kernel threads).
    """
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    if not raw:
        return None
    return [p.decode("utf-8", errors="ignore") for p in raw.split(b"\x00") if p]


def _classify(parts: List[str], allowlist: Set[str]) -> Set[str]:
    """Map a process's argv to the set of allowlist entries it represents.

    Returns the canonical names so the aggregator sees a stable
    `sleap-label`/`sleap-train`/`sleap-track` regardless of which shape
    the user invoked.
    """
    matches: Set[str] = set()
    if not parts:
        return matches
    argv0 = os.path.basename(parts[0])

    if argv0 in allowlist:
        matches.add(argv0)

    if argv0 == "sleap" and len(parts) > 1:
        candidate = f"sleap-{parts[1]}"
        if candidate in allowlist:
            matches.add(candidate)

    if argv0.startswith("python"):
        try:
            i = parts.index("-m")
        except ValueError:
            i = -1
        if 0 <= i and i + 2 < len(parts) and parts[i + 1] == "sleap.cli":
            candidate = f"sleap-{parts[i + 2]}"
            if candidate in allowlist:
                matches.add(candidate)

    return matches


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
        parts = _read_cmdline(os.path.join(proc_root, name, "cmdline"))
        if parts is None:
            continue
        seen |= _classify(parts, wanted)
        if seen >= wanted:
            break
    return seen
