"""Bounded reads of the allocator's own log file.

start.sh tees this container's entire stdout/stderr through `rotatelogs`
into LOG_DIR, and this module is the only way the allocator can show that
output: nothing mounts docker.sock, so it cannot run `docker logs` on
itself.

Flask-free on purpose -- the tailing and redaction logic is the part worth
testing, and keeping it out of the route module lets it test against
tmp_path with no app fixture.
"""
import os
import re
from pathlib import Path

from lablink_allocator_service.utils.ansi import strip_ansi

LOG_DIR = Path("/var/log/lablink")
LOG_BASENAME = "allocator.log"

# Matches what `rotatelogs -n 2` produces: the base name plus its circular
# sibling (allocator.log, allocator.log.1).
_ROTATION_GLOB = f"{LOG_BASENAME}*"

# Matches the CLI's _MANUAL_ALLOCATOR_TAIL so the web page and `lablink
# logs` show the same depth of history.
DEFAULT_MAX_LINES = 2000

# Enough bytes to cover DEFAULT_MAX_LINES of ordinary log output without
# reading a 64 MB file on every 5-second poll from the log page.
_TAIL_WINDOW_BYTES = 2 * 1024 * 1024

# cloudflared dumps its entire environment at INFO on startup (see
# start.sh), which puts the Postgres and admin passwords into this stream.
# The log page makes that stream readable to anyone holding the admin
# password, so mask before it leaves the process.
_SECRET_RE = re.compile(
    r"((?:\w*(?:PASSWORD|TOKEN|SECRET|KEY)\w*)\s*[=:]\s*)(\S+)",
    re.IGNORECASE,
)

_REDACTED = "***REDACTED***"


def redact_secrets(text: str) -> str:
    """Mask the values of secret-looking assignments, keeping the keys."""
    return _SECRET_RE.sub(rf"\1{_REDACTED}", text)


def _rotation_files(log_dir: Path) -> list[Path]:
    """Existing log files, oldest first.

    `rotatelogs -n` cycles a fixed list of names rather than shifting
    them, so the numeric suffix does not indicate age -- right after a
    rotation `allocator.log` is the *newer* file. Sorting by mtime keeps
    the concatenation chronological either way.
    """
    try:
        files = [p for p in log_dir.glob(_ROTATION_GLOB) if p.is_file()]
        # Build (mtime, path) pairs inside the guard, skipping entries
        # whose stat fails (e.g., file disappears between glob and here).
        pairs = []
        for p in files:
            try:
                pairs.append((p.stat().st_mtime, p))
            except OSError:
                continue
        return [p for _, p in sorted(pairs)]
    except OSError:
        return []


def _tail_bytes(path: Path, window: int) -> str:
    """Read at most `window` bytes from the end of `path`."""
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - window))
        return fh.read().decode("utf-8", errors="replace")


def read_allocator_log(
    log_dir: Path = LOG_DIR,
    max_lines: int = DEFAULT_MAX_LINES,
) -> str | None:
    """Last `max_lines` lines across the rotation set, cleaned and redacted.

    Returns None when there is no log file to read at all -- the caller
    turns that into a user-facing explanation rather than an error.
    """
    chunks = []
    for path in _rotation_files(log_dir):
        try:
            chunks.append(_tail_bytes(path, _TAIL_WINDOW_BYTES))
        except OSError:
            continue
    if not chunks:
        return None

    # The byte window can slice mid-line, leaving a fragmentary first
    # line. Harmless: _TAIL_WINDOW_BYTES holds far more than max_lines of
    # ordinary output, so the slice below almost always discards it.
    lines = "".join(chunks).splitlines()[-max_lines:]
    # Werkzeug colorizes non-2xx request lines, so this stream carries ANSI
    # escapes that the log box would render as literal junk. Client VM logs
    # reach the same template already clean -- vm_telemetry strips them at
    # ingestion -- so strip here to match.
    return redact_secrets(strip_ansi("\n".join(lines))) or None
