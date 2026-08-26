"""Ships this container's own log stream to the allocator.

Log shipping is host-side in the AWS topology (user_data's
log_shipper.sh tails ``docker logs``), but BYO clients have no
LabLink-controlled host process to rely on: run-locally boxes used a
detached CLI shipper that could die silently on operator laptops, and
hand-off clients (``register --no-run-locally``, e.g. a Run:AI
workload) never had any shipper at all — the container is its own
PID 1 with no docker daemon in sight. So BYO containers ship their own
stream: start.sh points fd 5 — the [tag]-prefixed output of every
service — at this worker's stdin when SHIP_LOGS=1.

That puts this worker IN the logging path, which imposes two hard
rules (lablink#304's silent tail stall is the cautionary tale):

* Passthrough first. Every stdin line is written to stdout (container
  PID-1 stdout, i.e. ``docker logs``) before anything else touches it,
  and the read loop never blocks on the network — shipping happens on
  a separate thread fed by a bounded drop-oldest queue.
* Fail open. Missing env degrades to pure passthrough, and start.sh's
  supervisor ``exec cat``s after repeated crashes — the worst case is
  logs visible in ``docker logs`` but absent from the allocator, never
  a frozen container.
"""

import os
import signal
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Callable

import requests

from lablink_client_service.http_utils import get_auth_headers, sanitize_url

BATCH_SIZE = 50
FLUSH_INTERVAL_S = 15
POLL_INTERVAL_S = 1.0
POST_TIMEOUT_S = 10
MAX_RETRIES = 3
RETRY_BACKOFF_S = (1, 2, 4)
# Bounds shipping memory during output bursts (a pip install can emit
# hundreds of lines/second). Overflow drops the OLDEST lines: when the
# allocator is unreachable for a while, the most recent output is what
# an operator debugging the client needs.
QUEUE_MAX_LINES = 2000
# The allocator routes a batch to the docker_logs column when log_group
# ends with "-docker" (vm_telemetry.py's receive_vm_logs); the
# "container" prefix names the source for anyone reading the DB.
LOG_GROUP = "container-docker"


def read_loop(queue: deque, stdin=None, stdout=None) -> None:
    """Forward stdin to stdout line by line, queueing stamped copies.

    The passthrough write happens FIRST and the loop touches nothing
    that can block indefinitely besides stdin itself, so ``docker
    logs`` output is byte-identical to running without this worker.
    Returns on EOF (container shutdown).
    """
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    # iter(readline, ""), not `for line in stdin`: file iteration may
    # read ahead into an internal buffer and sit on complete lines,
    # which in this seat delays every service's logs.
    for line in iter(stdin.readline, ""):
        stdout.write(line)
        stdout.flush()
        # Stamped at read time, not emission time — equivalent here
        # (the passthrough seat sees lines the moment services emit
        # them) and avoids parsing arbitrary service output.
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        queue.append(f"{ts} {line.rstrip()}")


def drain(queue: deque, max_items: int = BATCH_SIZE) -> list:
    """Pop up to ``max_items`` lines from the left of ``queue``."""
    batch: list = []
    while len(batch) < max_items:
        try:
            batch.append(queue.popleft())
        except IndexError:
            break
    return batch


def post_batch(
    *,
    base_url: str,
    vm_name: str,
    headers: dict,
    messages: list,
    retries: int = MAX_RETRIES,
    _sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """POST one batch to /api/vm-logs/<vm_name>. True on 2xx.

    Retries with backoff, then reports failure so the caller drops the
    batch. Unlike the deleted CLI shipper it never treats a 4xx as
    fatal: this worker is the only log channel BYO clients have and
    nothing respawns it for shipping-only failures, so a transient 401
    while the allocator's DB warms up must degrade to a dropped batch,
    not a permanently dead shipper.
    """
    url = f"{base_url}/api/vm-logs/{vm_name}"
    payload = {"log_group": LOG_GROUP, "messages": messages}
    for attempt in range(retries):
        if attempt:
            _sleep(RETRY_BACKOFF_S[attempt - 1])
        try:
            resp = requests.post(
                url, json=payload, headers=headers, timeout=POST_TIMEOUT_S
            )
            if 200 <= resp.status_code < 300:
                return True
        except requests.exceptions.RequestException:
            pass
    return False


def shipper_loop(
    queue: deque,
    stop_event: threading.Event,
    post_fn: Callable[[list, int], bool],
    *,
    _monotonic: Callable[[], float] = time.monotonic,
    poll_s: float = POLL_INTERVAL_S,
) -> None:
    """Flush the queue on the 50-line / 15-second rule until stopped.

    ``post_fn(messages, retries)`` does the actual POST. The stop path
    performs a final single-attempt flush (no backoff) so a graceful
    ``docker stop`` ships the tail inside docker's grace period.
    """
    last_flush = _monotonic()
    while True:
        stopped = stop_event.wait(poll_s)
        now = _monotonic()
        if not queue:
            last_flush = now
        elif (
            stopped
            or len(queue) >= BATCH_SIZE
            or now - last_flush >= FLUSH_INTERVAL_S
        ):
            retries = 1 if stopped else MAX_RETRIES
            while True:
                batch = drain(queue)
                if not batch:
                    break
                if not post_fn(batch, retries):
                    print(
                        f"ship_logs: dropped {len(batch)} lines after "
                        "retries",
                        file=sys.stderr,
                        flush=True,
                    )
            last_flush = now
        if stopped:
            return


def main() -> None:
    """Entry point for the ``ship_logs`` console script."""
    allocator_url = os.environ.get("ALLOCATOR_URL")
    client_secret = os.environ.get("CLIENT_SECRET")
    vm_name = os.environ.get("VM_NAME")
    if not (allocator_url and client_secret and vm_name):
        # Fail open: stay a pure passthrough so logging never depends
        # on registration plumbing being complete.
        print(
            "ship_logs: ALLOCATOR_URL/CLIENT_SECRET/VM_NAME not all set; "
            "passing lines through without shipping",
            file=sys.stderr,
            flush=True,
        )
        read_loop(deque(maxlen=1))
        return

    base_url = sanitize_url(allocator_url)
    headers = {"Content-Type": "application/json"}
    headers.update(get_auth_headers(client_secret))

    def post_fn(messages: list, retries: int) -> bool:
        return post_batch(
            base_url=base_url,
            vm_name=vm_name,
            headers=headers,
            messages=messages,
            retries=retries,
        )

    queue: deque = deque(maxlen=QUEUE_MAX_LINES)
    stop_event = threading.Event()
    signaled = threading.Event()

    def shipper() -> None:
        shipper_loop(queue, stop_event, post_fn)
        if signaled.is_set():
            # The main thread is blocked in readline and only docker's
            # SIGKILL would end it; exit here so `docker stop` is fast
            # and the final flush above still happened.
            os._exit(0)

    thread = threading.Thread(target=shipper, daemon=True)
    thread.start()

    def handle_stop(signum, _frame) -> None:
        signaled.set()
        stop_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, handle_stop)
        except (ValueError, AttributeError):
            pass

    print(
        f"ship_logs: forwarding to {base_url}/api/vm-logs/{vm_name}",
        file=sys.stderr,
        flush=True,
    )
    read_loop(queue)
    # EOF: every fd-5 writer is gone. Final flush, then exit.
    stop_event.set()
    thread.join(timeout=POST_TIMEOUT_S + 5)


if __name__ == "__main__":
    main()
