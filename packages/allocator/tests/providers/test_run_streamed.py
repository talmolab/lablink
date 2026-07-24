"""Tests for AWSProvider's _run_streamed helper — the Popen-based
streaming replacement for subprocess.run(capture_output=True) used by
provision_hosts/destroy_hosts to report incremental progress."""
from __future__ import annotations

import io
import subprocess
from unittest.mock import patch

import pytest

from lablink_allocator_service.providers.aws import (
    _CREATE_COMPLETE_RE,
    _run_streamed,
)


class _FakePopen:
    """Minimal stand-in for subprocess.Popen exposing just the surface
    _run_streamed uses: an iterable, closeable .stdout, a .stderr with
    .read(), and .wait() returning a returncode."""

    def __init__(self, stdout_text="", stderr_text="", returncode=0):
        self.stdout = io.StringIO(stdout_text)
        self.stderr = io.StringIO(stderr_text)
        self._returncode = returncode

    def wait(self):
        return self._returncode


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
            ["terraform", "apply"],
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
            ["terraform", "apply"],
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
                ["terraform", "apply"],
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
            ["terraform", "apply"],
            cwd="/tmp",
            resource_complete_re=_CREATE_COMPLETE_RE,
        )
    assert result.stdout == "line one\n"
