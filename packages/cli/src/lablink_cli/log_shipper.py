"""Ships docker container logs from a BYO client to the allocator.

Invoked as: ``python -m lablink_cli.log_shipper <env_file>``
by ``lablink register``. Reads CLIENT_SECRET / ALLOCATOR_URL / VM_NAME from
the env file written by register, batches ``docker logs --follow`` output,
and POSTs to ``/api/vm-logs/<hostname>``.
"""

from __future__ import annotations

import json
import os
import queue
import re
import signal
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request
from urllib.request import urlopen as _stdlib_urlopen

from lablink_cli.api import USER_AGENT
from lablink_cli.docker import Docker, default_docker


def load_env(env_file: Path) -> dict[str, str]:
    """Parse the BYO client.env file (KEY=VALUE per line, # comments)."""
    text = Path(env_file).read_text()
    env: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value
    return env


def read_last_shipped_ts(state_file: Path) -> str | None:
    """Return the timestamp of the last successfully shipped line, or None.

    Treats missing or corrupt state as None (first-attach behavior).
    """
    try:
        data = json.loads(Path(state_file).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    ts = data.get("last_shipped_ts")
    return ts if isinstance(ts, str) else None


def write_last_shipped_ts(state_file: Path, ts: str) -> None:
    """Persist last_shipped_ts atomically (write-and-rename)."""
    path = Path(state_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({"last_shipped_ts": ts}))
    tmp.replace(path)


MAX_RETRIES = 3
RETRY_BACKOFF_S = (1, 2, 4)  # sleep before retry attempt 1, 2, 3
# The allocator routes logs to the docker_logs column when log_group ends
# with "-docker"; cloud_init otherwise (main.py:851). Manual/BYO clients
# only ship docker container output, so use a name that satisfies the
# suffix check.
LOG_GROUP = "manual-docker"

PostResult = Literal["ok", "drop", "fatal"]


def post_batch(
    *,
    allocator_url: str,
    vm_name: str,
    client_secret: str,
    messages: list[str],
    log_group: str = LOG_GROUP,
    urlopen: Callable = _stdlib_urlopen,
    sleep: Callable[[float], None] = time.sleep,
) -> PostResult:
    """POST a batch of log lines to /api/vm-logs/<vm_name>.

    Returns ``"ok"`` on 2xx, ``"fatal"`` on 4xx (no retry — shipper should
    exit), and ``"drop"`` after MAX_RETRIES of 5xx or network failures.
    """
    url = f"{allocator_url.rstrip('/')}/api/vm-logs/{vm_name}"
    body = json.dumps({"log_group": log_group, "messages": messages}).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {client_secret}",
        # urllib's default "Python-urllib/x.y" is blocked with HTTP 403 by
        # Cloudflare-proxied allocators (see api.py's USER_AGENT) — post_batch
        # treats any 4xx as fatal, so without this every batch kills the
        # shipper on its first POST.
        "User-Agent": USER_AGENT,
    }

    for attempt in range(MAX_RETRIES):
        if attempt > 0:
            sleep(RETRY_BACKOFF_S[attempt - 1])
        try:
            req = Request(url, data=body, headers=headers, method="POST")
            with urlopen(req, timeout=10) as resp:
                if 200 <= resp.status < 300:
                    return "ok"
                continue
        except HTTPError as e:
            if 400 <= e.code < 500:
                return "fatal"  # bad secret / unknown hostname — exit
            continue
        except URLError:
            continue
    return "drop"


BATCH_SIZE = 50
FLUSH_INTERVAL_S = 15


def should_flush(*, buffer_len: int, elapsed_s: float) -> bool:
    """Return True if the buffer should be flushed now."""
    if buffer_len == 0:
        return False
    return buffer_len >= BATCH_SIZE or elapsed_s >= FLUSH_INTERVAL_S


CONTAINER_NAME = "lablink-client"

# Strip RFC3339Nano fractional seconds (e.g.
# 2026-05-28T14:23:01.123456789Z → 2026-05-28T14:23:01Z) so admin views
# aren't cluttered with nanosecond noise. Matches log_shipper.sh:101.
_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?Z (.*)$"
)


def parse_docker_line(line: str) -> tuple[str | None, str]:
    """Split a ``docker logs --timestamps`` line into ``(ts, message)``.

    Returns ``(None, line)`` if no timestamp prefix is present.
    """
    m = _TS_RE.match(line)
    if not m:
        return None, line
    return f"{m.group(1)}Z", m.group(2)


LOG_SHIPPER_DIR = Path.home() / ".lablink"
PID_FILE = LOG_SHIPPER_DIR / "log_shipper.pid"
STATE_FILE = LOG_SHIPPER_DIR / "log_shipper.state"
SELF_LOG_FILE = LOG_SHIPPER_DIR / "log_shipper.log"
FIRST_ATTACH_LOOKBACK_S = 60
CONTAINER_RESTART_WAIT_S = 5
INSPECT_RETRY_INTERVAL_S = 30
INSPECT_MAX_RETRIES = 5
# After this many consecutive "exited" inspections, give up — the container
# has stopped and docker is not restarting it, which means the user invoked
# `docker stop`. With `--restart unless-stopped`, a crashed container goes to
# "restarting" within ms, so consecutive "exited" reliably indicates user
# intent rather than a transient state.
MAX_EXITED_CONSECUTIVE = 3

SELF_LOG_MAX_BYTES = 1_000_000


def self_log(log_file: Path, message: str) -> None:
    """Append a timestamped line to the shipper's own diagnostic log.

    Rotates to <log>.1 (single rotation) when the file exceeds 1MB. This
    is the shipper's only error channel; it runs detached so stdout/stderr
    are discarded.
    """
    path = Path(log_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size >= SELF_LOG_MAX_BYTES:
        rotated = path.with_suffix(path.suffix + ".1")
        path.replace(rotated)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with path.open("a") as f:
        f.write(f"{ts} {message}\n")


def _initial_since() -> str:
    """RFC3339 timestamp ~1 minute ago, for first-ever shipper attach."""
    ts = datetime.now(timezone.utc) - timedelta(
        seconds=FIRST_ATTACH_LOOKBACK_S
    )
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


# Yielded when the flush window elapses with no new log line, so the read
# loop wakes up and re-evaluates should_flush().
TICK = object()


def _read_lines_from_popen(proc, *, timeout: float = FLUSH_INTERVAL_S):
    """Yield a Popen's stdout line by line, plus TICK on each idle timeout.

    A bare ``for line in proc.stdout`` only wakes when output arrives, so a
    container that logs a burst at startup and then goes quiet holds its
    buffer forever and the allocator never sees a single line. The shell
    shipper avoids this with ``read -t "$FLUSH_INTERVAL"``
    (log_shipper.sh:115); pipes aren't selectable on Windows — where BYO
    clients actually run — so a reader thread plus a queue is the portable
    equivalent.
    """
    if proc.stdout is None:
        return
    q: queue.Queue = queue.Queue()
    eof = object()

    def pump():
        try:
            for line in proc.stdout:
                q.put(line.rstrip("\n"))
        finally:
            q.put(eof)

    threading.Thread(target=pump, daemon=True).start()
    while True:
        try:
            item = q.get(timeout=timeout)
        except queue.Empty:
            yield TICK
            continue
        if item is eof:
            return
        yield item


def run_shipper(
    env_file: Path,
    *,
    _line_iter: Callable | None = None,
    _sleep: Callable[[float], None] = time.sleep,
    docker: Docker | None = None,
) -> None:
    """Main shipper loop. Returns when shipping should stop."""
    docker = docker or default_docker()
    env = load_env(env_file)
    allocator_url = env["ALLOCATOR_URL"]
    vm_name = env["VM_NAME"]
    client_secret = env["CLIENT_SECRET"]

    self_log(SELF_LOG_FILE, f"shipper starting for vm_name={vm_name}")

    since = read_last_shipped_ts(STATE_FILE) or _initial_since()
    self_log(SELF_LOG_FILE, f"attaching to docker logs --since {since}")

    # ---- Attach loop: re-runs if container restarts ----
    inspect_failures = 0
    exited_consecutive = 0
    while True:
        if _line_iter is not None:
            line_source = _line_iter()
            proc = None
        else:
            proc = docker.follow_logs(CONTAINER_NAME, since=since)
            line_source = _read_lines_from_popen(proc)

        buffer: list[str] = []
        buffer_first_ts: float | None = None
        last_ts_in_batch: str | None = None

        # ---- Inner read loop ----
        try:
            for line in line_source:
                # TICK means the flush window elapsed with no new line —
                # skip straight to the flush check below. should_flush()
                # already no-ops on an empty buffer.
                if line is not TICK:
                    ts, msg = parse_docker_line(line)
                    # Buffer the original tagged line, preserving the
                    # timestamp prefix so admin views show it (matches
                    # log_shipper.sh's docker --timestamps + sed pipeline).
                    if ts is not None:
                        buffer.append(f"{ts} {msg}")
                        last_ts_in_batch = ts
                    else:
                        buffer.append(msg)
                    if buffer_first_ts is None:
                        buffer_first_ts = time.monotonic()

                elapsed = (
                    time.monotonic() - buffer_first_ts
                    if buffer_first_ts is not None
                    else 0
                )
                if should_flush(
                    buffer_len=len(buffer), elapsed_s=elapsed
                ):
                    result = post_batch(
                        allocator_url=allocator_url,
                        vm_name=vm_name,
                        client_secret=client_secret,
                        messages=buffer,
                    )
                    if result == "ok" and last_ts_in_batch:
                        write_last_shipped_ts(
                            STATE_FILE, last_ts_in_batch
                        )
                    elif result == "fatal":
                        self_log(
                            SELF_LOG_FILE,
                            "POST returned fatal (4xx); exiting",
                        )
                        return
                    elif result == "drop":
                        self_log(
                            SELF_LOG_FILE,
                            f"dropped batch of {len(buffer)} after retries",
                        )
                    buffer = []
                    buffer_first_ts = None
                    last_ts_in_batch = None
        finally:
            if proc is not None:
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except Exception:
                    pass

        # Flush any tail buffer before deciding whether to reconnect.
        if buffer:
            result = post_batch(
                allocator_url=allocator_url,
                vm_name=vm_name,
                client_secret=client_secret,
                messages=buffer,
            )
            if result == "ok" and last_ts_in_batch:
                write_last_shipped_ts(STATE_FILE, last_ts_in_batch)
            elif result == "fatal":
                self_log(
                    SELF_LOG_FILE,
                    "POST returned fatal during tail flush; exiting",
                )
                return

        # docker logs --follow exited. Inspect to decide what to do.
        status = docker.container_status(CONTAINER_NAME)
        self_log(
            SELF_LOG_FILE, f"docker logs ended; container status={status}"
        )
        if status == "missing":
            self_log(SELF_LOG_FILE, "container missing; exiting")
            return
        if status == "daemon_error":
            inspect_failures += 1
            if inspect_failures >= INSPECT_MAX_RETRIES:
                self_log(
                    SELF_LOG_FILE,
                    "daemon unreachable after max retries; exiting",
                )
                return
            _sleep(INSPECT_RETRY_INTERVAL_S)
            continue
        inspect_failures = 0
        if status == "exited":
            exited_consecutive += 1
            if exited_consecutive >= MAX_EXITED_CONSECUTIVE:
                self_log(
                    SELF_LOG_FILE,
                    f"container stayed exited for {exited_consecutive} "
                    "consecutive checks; treating as user-initiated stop; "
                    "exiting",
                )
                return
            _sleep(CONTAINER_RESTART_WAIT_S)
        elif status == "restarting":
            # docker is bringing it back — don't count toward the give-up
            # threshold, just wait and reconnect.
            exited_consecutive = 0
            _sleep(CONTAINER_RESTART_WAIT_S)
        else:
            # status == "running" → reconnect immediately
            exited_consecutive = 0
        # update since for the reconnect so we don't re-ship
        new_since = read_last_shipped_ts(STATE_FILE)
        if new_since:
            since = new_since
        # If _line_iter is set (test), exit the outer loop after one pass to
        # keep tests deterministic.
        if _line_iter is not None:
            return


def _handle_shutdown(signum, _frame) -> None:
    """SIGTERM/SIGINT handler: unlink PID file and exit cleanly."""
    try:
        PID_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    self_log(SELF_LOG_FILE, f"received signal {signum}; exiting")
    sys.exit(0)


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m lablink_cli.log_shipper <env_file>``."""
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print(
            "usage: python -m lablink_cli.log_shipper <env_file>",
            file=sys.stderr,
        )
        return 2

    env_file = Path(args[0])

    LOG_SHIPPER_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))

    # Best-effort signal handlers. Windows lacks SIGTERM in the standard
    # sense; signal.signal(SIGTERM, ...) works on POSIX but is a no-op or
    # raises on Windows for some signals — guard with try/except.
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handle_shutdown)
        except (ValueError, AttributeError):
            pass

    try:
        run_shipper(env_file)
    finally:
        try:
            PID_FILE.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
