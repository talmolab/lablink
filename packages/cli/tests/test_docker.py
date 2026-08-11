"""Tests for the docker adapter."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from lablink_cli.docker import (
    Docker,
    DockerDaemonError,
    DockerUnavailable,
    NullDocker,
    Result,
)


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=["docker"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_result_ok():
    assert Result(0).ok is True
    assert Result(1).ok is False


def test_volume_exists_true_on_zero_exit():
    with patch("lablink_cli.docker.subprocess.run", return_value=_completed(0)):
        assert Docker().volume_exists("vol") is True


def test_volume_exists_false_on_nonzero_exit():
    with patch("lablink_cli.docker.subprocess.run", return_value=_completed(1)):
        assert Docker().volume_exists("vol") is False


def test_container_status_maps_running():
    with patch(
        "lablink_cli.docker.subprocess.run",
        return_value=_completed(0, stdout="running\n"),
    ):
        assert Docker().container_status("c") == "running"


def test_container_status_maps_unknown_state_to_exited():
    with patch(
        "lablink_cli.docker.subprocess.run",
        return_value=_completed(0, stdout="paused\n"),
    ):
        assert Docker().container_status("c") == "exited"


def test_container_status_missing_when_no_such_object():
    with patch(
        "lablink_cli.docker.subprocess.run",
        return_value=_completed(1, stderr="Error: No such object: c"),
    ):
        assert Docker().container_status("c") == "missing"


def test_container_status_daemon_error_on_timeout():
    with patch(
        "lablink_cli.docker.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="docker", timeout=10),
    ):
        assert Docker().container_status("c") == "daemon_error"


def test_inspect_format_returns_empty_when_absent():
    with patch("lablink_cli.docker.subprocess.run", return_value=_completed(1)):
        assert Docker().inspect_format("c", "{{.Id}}") == ""


def test_daemon_info_raises_on_failure():
    with patch(
        "lablink_cli.docker.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "docker"),
    ):
        with pytest.raises(DockerDaemonError):
            Docker().daemon_info("{{.CgroupDriver}}")


def test_logs_merges_stderr_when_asked():
    with patch("lablink_cli.docker.subprocess.run") as run:
        run.return_value = _completed(0, stdout="line")
        Docker().logs("c", tail=30, merge_stderr=True)
    kwargs = run.call_args.kwargs
    assert kwargs["stderr"] is subprocess.STDOUT
    assert "--tail" in run.call_args.args[0]


def test_compose_passes_workdir_as_cwd():
    with patch("lablink_cli.docker.subprocess.run") as run:
        run.return_value = _completed(0)
        Docker().compose("/tmp/x", "ps")
    assert run.call_args.kwargs["cwd"] == "/tmp/x"
    assert run.call_args.args[0] == ["docker", "compose", "ps"]


def test_compose_without_workdir_passes_no_cwd():
    with patch("lablink_cli.docker.subprocess.run") as run:
        run.return_value = _completed(0)
        Docker().compose(None, "version")
    assert run.call_args.kwargs["cwd"] is None


def test_require_raises_when_docker_absent():
    with patch("lablink_cli.docker.shutil.which", return_value=None):
        with pytest.raises(DockerUnavailable):
            Docker().require()


def test_verbs_raise_docker_unavailable_when_absent():
    with patch("lablink_cli.docker.shutil.which", return_value=None):
        with pytest.raises(DockerUnavailable):
            Docker().volume_exists("vol")


def test_null_docker_reports_nothing_present():
    null = NullDocker()
    assert null.path() is None
    assert null.available() is False
    assert null.volume_exists("vol") is False
    assert null.container_status("c") == "missing"
    assert null.inspect_format("c", "{{.Id}}") == ""


def test_null_docker_mimics_the_old_guard_result():
    result = NullDocker().compose(None, "ps")
    assert result.returncode == 1
    assert "No such container" in result.stderr
