"""Errors-only filtering for the two admin log surfaces.

Both streams are heterogeneous. A client VM's shipped output mixes Python
records with KasmVNC/XFCE output and shell echoes; the allocator's own
stream mixes its Flask records with cloudflared, postgres and gunicorn.
(Not nginx: start.sh execs it, and its errors go to Debian's default
/var/log/nginx/error.log rather than into allocator.log.)

So the rule matches the level markers those producers actually emit --
Python's uppercase `%(levelname)s` tokens, cloudflared's zerolog
three-letter levels (`ERR`/`FTL`) and postgres' `PANIC`. It is a
recall-first rule; what keeps it honest is being case-sensitive, plus a
short denylist. See _ERROR_RE and BENIGN_ERROR_PATTERNS.

Flask-free on purpose, like log_tail.py next door: the rule is the part
worth testing, and keeping it out of the route modules lets it test
against plain strings with no app fixture.
"""

import re

# Case-sensitive on purpose. A case-insensitive `error` matches the client
# startup script's happy path -- `--retry-all-errors` (start.sh:45,57,133)
# and `send_status "error"` (89,173) -- which would fill the error view
# with healthy lines. WARNING is deliberately excluded. The word
# boundaries matter too: `\bERR\b` does not fire inside `STDERR`.
_ERROR_RE = re.compile(r"\b(?:ERROR|CRITICAL|FATAL|ERR|FTL|PANIC)\b")

_TRACEBACK_HEADER = "Traceback (most recent call last)"

# What CPython prints between the two halves of a chained traceback. The
# half that follows is the one naming the fault an admin needs (e.g. the
# requests ConnectionError with its host and port, not the inner
# ConnectionRefusedError), so both halves belong to the same kept block.
_CHAIN_MARKERS = (
    "During handling of the above exception, another exception occurred:",
    "The above exception was the direct cause of the following exception:",
)

# Strips an optional leading RFC3339 timestamp and an optional `[tag] `
# source prefix, capturing the tag for the continuation walk. Client lines
# carry both by the time they reach the allocator: the log shipper prepends
# the timestamp (log_shipper.py:284) and start.sh pipes every service
# through `sed 's/^/[tag] /'`. Without this, a traceback's indented frames
# do not start at column 0 and the continuation walk below would drop every
# frame for every client VM.
_PREFIX_RE = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*\s+)?(?:\[(?P<tag>[\w.-]+)\]\s?)?"
)

# ERROR-level lines from the client's reporting path: a report was lost
# after its retries were exhausted, which does not affect the VM's own
# usability -- the desktop is still serving and the student is unaffected.
# Suppressed here rather than downgraded at the source because client code
# ships inside a released Docker image, so a level change would only reach
# VMs launched after the next client release; this reaches every
# already-running VM on allocator restart. Substring-matched against the
# whole line, so the `[tag] ` prefix and the f-string tails do not matter.
# A real failure diagnosis never belongs here (see test_log_filter.py's
# drift test, and the nvidia-smi entry this list used to carry).
BENIGN_ERROR_PATTERNS: tuple[str, ...] = (
    "Failed to report GPU health after",  # check_gpu.py:112
    "Failed to update in-use status after",  # update_inuse_status.py:114
    "Push failed; will retry next interval",  # monitoring/__main__.py:174
)


def _body(line: str) -> str:
    """Return *line* with any timestamp / source-tag prefix removed."""
    return _PREFIX_RE.sub("", line, count=1)


def _tag(line: str) -> str | None:
    """Return *line*'s `[tag]` source prefix, or None if it carries none."""
    match = _PREFIX_RE.match(line)
    return match.group("tag") if match else None


def _traceback_indices(lines: list[str], start: int) -> list[int]:
    """Indices of the traceback belonging to the error line at *start*.

    The client's shipped stream interleaves by design: start.sh:14 dups
    stdout to fd 5 and every service then writes its own
    `... | sed -u 's/^/[tag] /' >&5 &` pipeline into it concurrently, so a
    `[kasmvnc]` or `[xstartup]` line landing in the middle of an `[agent]`
    traceback is the normal condition. When the error line carries a tag,
    only lines with that same tag count as continuation and foreign lines
    are stepped over. When it does not (the allocator's own stream, a bare
    tee/rotatelogs pipeline that is not interleaved), any indented line
    counts, as before.

    ponytail: an *untagged* interleaved stream can still mis-associate, and
    a tagged traceback whose terminal line somehow lost its tag loses that
    line. Neither shipped stream can produce either -- one service's lines
    all pass through one sed -- and the frame-count guard below keeps the
    damage to a dropped line rather than a foreign line presented as the
    exception. Tag every producer if that ever stops being true.

    Args:
        lines: Every line of the log, in stream order.
        start: Index of the kept error line whose traceback to collect.

    Returns:
        The indices to keep, ascending. Empty when no traceback follows.
    """
    tag = _tag(lines[start])
    claimed: list[int] = []
    i = start + 1
    while i < len(lines) and _body(lines[i]).startswith(_TRACEBACK_HEADER):
        claimed.append(i)
        i += 1
        frames = 0
        while i < len(lines):
            if tag is not None and _tag(lines[i]) != tag:
                i += 1  # interleaved foreign line; not ours, not the end
                continue
            if not _body(lines[i])[:1].isspace():
                break
            claimed.append(i)  # a stack frame
            frames += 1
            i += 1
        # The terminal `SomeError: msg`, but only once a frame has actually
        # been consumed -- that guard is what stops an unrelated line from
        # being presented as the exception when the tag logic cannot help.
        if frames and i < len(lines):
            claimed.append(i)
            i += 1
        # A chained traceback continues after a blank line and a marker.
        # Hold that filler until a header really follows, so a plain
        # trailing blank line is not swept into the output.
        j = i
        filler: list[int] = []
        while j < len(lines):
            if tag is not None and _tag(lines[j]) != tag:
                j += 1
                continue
            body = _body(lines[j]).strip()
            if body and body not in _CHAIN_MARKERS:
                break
            filler.append(j)
            j += 1
        if j < len(lines) and _body(lines[j]).startswith(_TRACEBACK_HEADER):
            claimed.extend(filler)
            i = j
        else:
            break
    return claimed


def is_error_line(line: str) -> bool:
    """True if *line* carries an uppercase error level and is not benign."""
    if not _ERROR_RE.search(line):
        return False
    return not any(p in line for p in BENIGN_ERROR_PATTERNS)


def filter_errors(text: str | None) -> str | None:
    """Keep only the error lines of *text*, with their tracebacks attached.

    Returns None for None -- there is no log at all -- and "" when the log
    had lines but none were errors. Callers render those two cases
    differently.

    Args:
        text: The raw log blob, or None when no log exists.

    Returns:
        The kept lines joined by newlines, "" if none matched, or None.
    """
    if text is None:
        return None

    lines = text.splitlines()
    # Indices rather than a running output list: a foreign line stepped
    # over inside a traceback walk stays eligible here, so an interleaved
    # `[kasmvnc] ERROR ...` is still kept on its own account instead of
    # being swallowed by the walk it interrupted.
    keep: set[int] = set()
    for i, line in enumerate(lines):
        if i in keep or not is_error_line(line):
            continue
        keep.add(i)
        # A logger.exception record puts its traceback on the lines that
        # follow, none of which carry a level token of their own.
        keep.update(_traceback_indices(lines, i))
    return "\n".join(lines[i] for i in sorted(keep))
