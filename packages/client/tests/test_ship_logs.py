"""Tests for the in-container log shipper (BYO clients)."""

import io
import re
import threading
from collections import deque
from unittest.mock import MagicMock, patch

import requests

from lablink_client_service import ship_logs
from lablink_client_service.ship_logs import (
    BATCH_SIZE,
    LOG_GROUP,
    drain,
    post_batch,
    read_loop,
    shipper_loop,
)


class TestReadLoop:
    def test_passthrough_is_byte_identical_and_ordered(self):
        src = "[start] one\n[agent] two\n[kasmvnc] three\n"
        stdout = io.StringIO()
        q: deque = deque()
        read_loop(q, stdin=io.StringIO(src), stdout=stdout)
        assert stdout.getvalue() == src

    def test_queued_copies_are_timestamped(self):
        q: deque = deque()
        read_loop(q, stdin=io.StringIO("hello\n"), stdout=io.StringIO())
        assert len(q) == 1
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z hello$", q[0]
        )

    def test_overflow_drops_oldest_but_passthrough_survives(self):
        src = "".join(f"line {i}\n" for i in range(10))
        stdout = io.StringIO()
        q: deque = deque(maxlen=3)
        read_loop(q, stdin=io.StringIO(src), stdout=stdout)
        assert stdout.getvalue() == src  # passthrough never drops
        assert [line.split(" ", 1)[1] for line in q] == [
            "line 7", "line 8", "line 9",
        ]


class TestDrain:
    def test_drains_in_batches_leaving_remainder(self):
        q = deque(range(BATCH_SIZE + 2))
        first = drain(q)
        assert len(first) == BATCH_SIZE
        assert drain(q) == [BATCH_SIZE, BATCH_SIZE + 1]
        assert drain(q) == []


class TestPostBatch:
    def test_posts_to_vm_logs_with_docker_suffix_group(self):
        resp = MagicMock(status_code=200)
        with patch.object(ship_logs.requests, "post", return_value=resp) as post:
            ok = post_batch(
                base_url="http://alloc",
                vm_name="runai-client-2",
                headers={"Authorization": "Bearer sekrit"},
                messages=["a"],
            )
        assert ok
        assert post.call_args.args == ("http://alloc/api/vm-logs/runai-client-2",)
        payload = post.call_args.kwargs["json"]
        # The allocator routes to the docker_logs column only when the
        # group ends with "-docker" (receive_vm_logs).
        assert payload["log_group"] == LOG_GROUP
        assert LOG_GROUP.endswith("-docker")
        assert payload["messages"] == ["a"]

    def test_retries_then_reports_failure_without_raising(self):
        err = requests.exceptions.ConnectionError("nope")
        with patch.object(ship_logs.requests, "post", side_effect=err) as post:
            ok = post_batch(
                base_url="http://alloc",
                vm_name="vm",
                headers={},
                messages=["a"],
                _sleep=lambda s: None,
            )
        assert not ok
        assert post.call_count == ship_logs.MAX_RETRIES

    def test_4xx_is_dropped_not_fatal(self):
        # A 4xx must not kill this worker — nothing respawns it for
        # shipping-only failures. post_batch just reports failure.
        resp = MagicMock(status_code=401)
        with patch.object(ship_logs.requests, "post", return_value=resp):
            ok = post_batch(
                base_url="http://alloc",
                vm_name="vm",
                headers={},
                messages=["a"],
                _sleep=lambda s: None,
            )
        assert not ok

    def test_single_retry_mode_for_final_flush(self):
        err = requests.exceptions.ConnectionError("nope")
        with patch.object(ship_logs.requests, "post", side_effect=err) as post:
            post_batch(
                base_url="http://alloc",
                vm_name="vm",
                headers={},
                messages=["a"],
                retries=1,
                _sleep=lambda s: None,
            )
        assert post.call_count == 1


class TestShipperLoop:
    def test_stop_flushes_everything_with_single_retry(self):
        q = deque(f"l{i}" for i in range(BATCH_SIZE + 2))
        stop = threading.Event()
        stop.set()
        calls = []
        shipper_loop(
            q, stop, lambda msgs, retries: calls.append((msgs, retries)) or True,
            poll_s=0,
        )
        assert [len(m) for m, _ in calls] == [BATCH_SIZE, 2]
        assert all(retries == 1 for _, retries in calls)
        assert not q

    def test_interval_elapse_flushes_small_buffer(self):
        q = deque(["only-line"])
        stop = threading.Event()
        calls = []
        clock = iter([0.0, 20.0, 20.0, 40.0])  # jumps past FLUSH_INTERVAL_S

        def post(msgs, retries):
            calls.append(msgs)
            stop.set()  # end the loop after the first flush
            return True

        shipper_loop(q, stop, post, _monotonic=lambda: next(clock), poll_s=0)
        assert calls and calls[0] == ["only-line"]

    def test_failed_post_drops_batch_and_continues(self, capsys):
        q = deque(["a", "b"])
        stop = threading.Event()
        stop.set()
        shipper_loop(q, stop, lambda msgs, retries: False, poll_s=0)
        assert not q  # dropped, not retained
        assert "dropped 2 lines" in capsys.readouterr().err
