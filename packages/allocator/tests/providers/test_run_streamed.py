"""Tests for AWSProvider's _run_streamed helper — the Popen-based
streaming replacement for subprocess.run(capture_output=True) used by
provision_hosts/destroy_hosts to report incremental progress."""
from __future__ import annotations

import io
import subprocess
import threading
import time
from unittest.mock import patch

import pytest

from lablink_allocator_service.providers.aws import (
    _CREATE_COMPLETE_RE,
    _DESTROY_COMPLETE_RE,
    _run_streamed,
)


class _DelayedReader:
    """Wraps a StringIO's .read() with an optional sleep, so tests can
    force the stderr-draining background thread to still be in-flight
    when the main thread raises -- proving _run_streamed's
    stderr_thread.join() in its finally block actually waits for it
    rather than leaking a running thread."""

    def __init__(self, text="", delay=0.0):
        self._io = io.StringIO(text)
        self._delay = delay

    def read(self):
        if self._delay:
            time.sleep(self._delay)
        return self._io.read()


class _FakePopen:
    """Minimal stand-in for subprocess.Popen exposing just the surface
    _run_streamed uses: an iterable, closeable .stdout, a .stderr with
    .read(), .wait() returning a returncode, and .kill()."""

    def __init__(
        self, stdout_text="", stderr_text="", returncode=0, stderr_delay=0.0
    ):
        self.stdout = io.StringIO(stdout_text)
        self.stderr = _DelayedReader(stderr_text, delay=stderr_delay)
        self._returncode = returncode
        self.killed = False
        self.wait_called = False

    def wait(self):
        self.wait_called = True
        return self._returncode

    def kill(self):
        self.killed = True


def test_run_streamed_invokes_callback_per_matching_line():
    stdout_text = (
        "aws_instance.client[0]: Creating...\n"
        "aws_instance.client[0]: Still creating... [10s elapsed]\n"
        "aws_instance.client[0]: Creation complete after 12s [id=i-1]\n"
        "aws_instance.client[1]: Creating...\n"
        "aws_instance.client[1]: Creation complete after 15s [id=i-2]\n"
    )
    calls = []
    with patch(
        "lablink_allocator_service.providers.aws.subprocess.Popen",
        return_value=_FakePopen(stdout_text=stdout_text, returncode=0),
    ):
        result = _run_streamed(
            ["tofu", "apply"],
            cwd="/tmp",
            resource_complete_re=_CREATE_COMPLETE_RE,
            on_resource_complete=lambda: calls.append(1),
        )

    assert len(calls) == 2
    assert result.stdout == stdout_text
    assert result.returncode == 0


def test_run_streamed_strips_ansi_before_matching():
    """A 'Creation complete after' line wrapped in ANSI color codes must
    still match — matching is done on an ANSI-stripped copy of each
    line, not the raw line."""
    stdout_text = (
        "\x1b[32maws_instance.client[0]: Creation complete after 12s "
        "[id=i-1]\x1b[0m\n"
    )
    calls = []
    with patch(
        "lablink_allocator_service.providers.aws.subprocess.Popen",
        return_value=_FakePopen(stdout_text=stdout_text, returncode=0),
    ):
        _run_streamed(
            ["tofu", "apply"],
            cwd="/tmp",
            resource_complete_re=_CREATE_COMPLETE_RE,
            on_resource_complete=lambda: calls.append(1),
        )
    assert len(calls) == 1


def test_run_streamed_raises_on_nonzero_exit_with_stdout_stderr_populated():
    with patch(
        "lablink_allocator_service.providers.aws.subprocess.Popen",
        return_value=_FakePopen(
            stdout_text="some output\n", stderr_text="boom", returncode=1,
        ),
    ):
        with pytest.raises(subprocess.CalledProcessError) as exc_info:
            _run_streamed(
                ["tofu", "apply"],
                cwd="/tmp",
                resource_complete_re=_CREATE_COMPLETE_RE,
            )
    assert exc_info.value.output == "some output\n"
    assert exc_info.value.stderr == "boom"


def test_run_streamed_works_with_no_callback():
    """on_resource_complete is optional — omitting it must not raise."""
    with patch(
        "lablink_allocator_service.providers.aws.subprocess.Popen",
        return_value=_FakePopen(stdout_text="line one\n", returncode=0),
    ):
        result = _run_streamed(
            ["tofu", "apply"],
            cwd="/tmp",
            resource_complete_re=_CREATE_COMPLETE_RE,
        )
    assert result.stdout == "line one\n"


def test_run_streamed_matches_multi_minute_durations():
    """Terraform formats durations under a minute as plain seconds
    ('12s'), but a minute or longer as 'MmSs' (e.g. '5m2s'), and past an
    hour as 'HhMmSs'. A regex anchored on \\d+s alone silently never
    matches the longer forms — this is a real bug found via an actual
    destroy of 5 VMs: the VMs each took 5-7 minutes to destroy, so their
    "Destruction complete after 5m2s"-style lines never matched and the
    progress counter never incremented for them, while the sub-minute
    supporting resources (key pair, IAM role, etc. — "0s"/"1s") did,
    producing a progress bar that looked stuck despite real progress."""
    stdout_text = (
        "aws_instance.lablink_vm[4]: Destruction complete after 5m2s\n"
        "aws_instance.lablink_vm[3]: Destruction complete after 5m53s\n"
        "aws_instance.lablink_vm[1]: Destruction complete after 6m43s\n"
        "aws_instance.lablink_vm[0]: Destruction complete after 6m53s\n"
        "aws_instance.lablink_vm[2]: Destruction complete after 7m3s\n"
        "aws_key_pair.lablink_key_pair: Destruction complete after 0s\n"
    )
    calls = []
    with patch(
        "lablink_allocator_service.providers.aws.subprocess.Popen",
        return_value=_FakePopen(stdout_text=stdout_text, returncode=0),
    ):
        _run_streamed(
            ["tofu", "apply"],
            cwd="/tmp",
            resource_complete_re=_DESTROY_COMPLETE_RE,
            on_resource_complete=lambda: calls.append(1),
        )
    assert len(calls) == 6


def test_run_streamed_matches_multi_minute_durations_for_create_too():
    """Companion to the destroy-side multi-minute test above: the same
    duration format applies to `terraform apply` (VM creation can also
    exceed a minute), and _CREATE_COMPLETE_RE shares _DURATION_RE with
    _DESTROY_COMPLETE_RE — this guards against a future edit that fixes
    one pattern but not the other."""
    stdout_text = (
        "aws_instance.client[0]: Creation complete after 1m36s [id=i-1]\n"
        "aws_instance.client[1]: Creation complete after 45s [id=i-2]\n"
    )
    calls = []
    with patch(
        "lablink_allocator_service.providers.aws.subprocess.Popen",
        return_value=_FakePopen(stdout_text=stdout_text, returncode=0),
    ):
        _run_streamed(
            ["tofu", "apply"],
            cwd="/tmp",
            resource_complete_re=_CREATE_COMPLETE_RE,
            on_resource_complete=lambda: calls.append(1),
        )
    assert len(calls) == 2


def test_run_streamed_kills_process_and_still_cleans_up_when_callback_raises():
    """Mirrors subprocess.run's `with Popen(...): ... except: process.kill();
    raise` contract: if on_resource_complete raises (e.g. a transient DB
    write failure while recording progress during a long terraform apply),
    the child process must be killed immediately rather than left running
    to keep mutating real infrastructure, and cleanup (stdout close,
    proc.wait(), stderr-thread join) must still happen so nothing is
    leaked -- while the original exception propagates unchanged."""
    stdout_text = (
        "aws_instance.client[0]: Creation complete after 12s [id=i-1]\n"
        "aws_instance.client[1]: Creation complete after 15s [id=i-2]\n"
    )
    # stderr_delay keeps the background drain thread asleep long enough
    # that it is still alive when the callback raises, so joining it
    # afterwards is a meaningful assertion rather than a no-op race.
    fake_popen = _FakePopen(
        stdout_text=stdout_text,
        stderr_text="some stderr output",
        returncode=0,
        stderr_delay=0.05,
    )

    boom = RuntimeError("transient DB error")

    def _on_complete():
        raise boom

    started_threads: list[threading.Thread] = []
    real_thread = threading.Thread

    def _spy_thread(*args, **kwargs):
        t = real_thread(*args, **kwargs)
        started_threads.append(t)
        return t

    with patch(
        "lablink_allocator_service.providers.aws.subprocess.Popen",
        return_value=fake_popen,
    ), patch(
        "lablink_allocator_service.providers.aws.threading.Thread",
        side_effect=_spy_thread,
    ):
        with pytest.raises(RuntimeError) as exc_info:
            _run_streamed(
                ["tofu", "apply"],
                cwd="/tmp",
                resource_complete_re=_CREATE_COMPLETE_RE,
                on_resource_complete=_on_complete,
            )

    # (a) the original exception propagates unchanged
    assert exc_info.value is boom
    # (b) the child process was killed rather than left running
    assert fake_popen.killed is True
    # (c) cleanup still happened: stdout closed, wait() called, and the
    # stderr-draining thread was joined (not left running / leaked)
    assert fake_popen.stdout.closed
    assert fake_popen.wait_called is True
    assert len(started_threads) == 1
    assert not started_threads[0].is_alive()
