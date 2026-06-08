"""Active-window sampler.

Polls `xdotool getactivewindow getwindowname` and buckets the title (which
we never store) into one of four buckets. Returns "other" when xdotool is
absent, the call fails, or no subject pattern is configured — degraded
behaviour, not a crash.
"""

import logging
import subprocess
from typing import Iterable

logger = logging.getLogger(__name__)

TERMINAL_PATS = ("xterm", "terminal", "files", "thunar")
BROWSER_PATS = ("firefox", "chrome", "chromium")

# Module-level latch so the "xdotool not installed" warning fires once
# at startup instead of every 2 s sampling tick. A missing binary is a
# permanent install-time problem — repeating the warning would just spam
# the log without adding information.
_xdotool_missing_warned = False


def _get_title() -> str | None:
    global _xdotool_missing_warned
    try:
        out = subprocess.run(
            ["xdotool", "getactivewindow", "getwindowname"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if out.returncode != 0:
            return None
        return out.stdout.strip()
    except FileNotFoundError:
        if not _xdotool_missing_warned:
            logger.warning(
                "xdotool not found on PATH; active-window bucket will stay "
                "at 'other' for the lifetime of this agent. Install xdotool "
                "in the client image to record seconds_in_subject_software."
            )
            _xdotool_missing_warned = True
        return None
    except subprocess.TimeoutExpired as e:
        logger.debug("xdotool probe timed out: %s", e)
        return None


def sample(subject_patterns: Iterable[str]) -> str:
    """Return the bucket name for the currently focused window.

    Args:
        subject_patterns: lower-cased substrings that, when contained in the
            title, mark it as the tutorial app (e.g. ["sleap"], ["deeplabcut"]).
            An empty iterable disables subject matching entirely.

    Returns:
        One of "subject" / "terminal" / "browser" / "other".
    """
    title = _get_title()
    if not title:
        return "other"
    title_l = title.lower()
    subj = [p.lower() for p in subject_patterns]
    if subj and any(p in title_l for p in subj):
        return "subject"
    if any(p in title_l for p in TERMINAL_PATS):
        return "terminal"
    if any(p in title_l for p in BROWSER_PATS):
        return "browser"
    return "other"
