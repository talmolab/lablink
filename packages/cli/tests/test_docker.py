"""Tests for the docker adapter."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

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


def test_container_status_daemon_error_when_docker_binary_missing():
    """Restored behavior: unlike other verbs, container_status has no
    require() guard. Its own subprocess.TimeoutExpired/OSError handler
    already covers a missing binary, mapping it to "daemon_error" — a
    normal return value, not a raised DockerUnavailable.
    """
    with patch("lablink_cli.docker.shutil.which", return_value=None), patch(
        "lablink_cli.docker.subprocess.run",
        side_effect=FileNotFoundError("docker"),
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


def test_logs_swallows_missing_binary_as_a_failed_result():
    """Like container_status, logs() has no require() guard: a docker
    binary missing from PATH surfaces as an ordinary non-zero Result, not
    a raised DockerUnavailable — callers that never expected an exception
    here (fetch_manual_allocator_logs, and Task 7's log-tailing helpers)
    depend on this. Patches shutil.which too so a real docker install on
    the test machine can't mask a reintroduced require() call — that guard
    checks PATH, not subprocess.run, so patching only subprocess.run isn't
    enough to exercise it."""
    with patch("lablink_cli.docker.shutil.which", return_value=None), patch(
        "lablink_cli.docker.subprocess.run",
        side_effect=FileNotFoundError("docker"),
    ):
        result = Docker().logs("c")
    assert result.returncode == 1
    assert not result.ok


def test_follow_logs_builds_base_argv():
    # Ported from log_shipper.TestOpenDockerLogs.test_builds_command_with_since
    # (Task 5) — the container-name-only shape of that same argv.
    with patch("lablink_cli.docker.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        Docker().follow_logs("lablink-client")
    argv = mock_popen.call_args.args[0]
    assert argv == [
        "docker",
        "logs",
        "--follow",
        "--timestamps",
        "lablink-client",
    ]


def test_follow_logs_includes_since_before_name():
    # Ported from
    # log_shipper.TestOpenDockerLogs.test_builds_command_with_since.
    with patch("lablink_cli.docker.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        Docker().follow_logs(
            "lablink-client", since="2026-08-12T00:00:00Z"
        )
    argv = mock_popen.call_args.args[0]
    since_idx = argv.index("--since")
    assert argv[since_idx + 1] == "2026-08-12T00:00:00Z"
    assert argv.index("lablink-client") > since_idx + 1


def test_follow_logs_omits_since_when_none():
    # Ported from log_shipper.TestOpenDockerLogs.test_omits_since_when_none.
    with patch("lablink_cli.docker.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        Docker().follow_logs("lablink-client", since=None)
    argv = mock_popen.call_args.args[0]
    assert "--since" not in argv


def test_follow_logs_popen_kwargs():
    """Line-buffering and merged streams are load-bearing for the shipper's
    incremental reads (_read_lines_from_popen) — not covered by the argv
    tests above, so assert on them directly."""
    with patch("lablink_cli.docker.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        Docker().follow_logs("lablink-client")
    kwargs = mock_popen.call_args.kwargs
    assert kwargs["stdout"] is subprocess.PIPE
    assert kwargs["stderr"] is subprocess.STDOUT
    assert kwargs["text"] is True
    assert kwargs["bufsize"] == 1


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


def test_null_docker_logs_does_not_shell_out():
    # logs() calls subprocess.run directly rather than routing through
    # _run, so it needs its own override or a NullDocker would silently
    # invoke the real `docker` binary.
    with patch("lablink_cli.docker.subprocess.run") as run:
        result = NullDocker().logs("c", tail=30)
    run.assert_not_called()
    assert result.returncode == 1
    assert "No such container" in result.stderr


def test_log_shipper_no_longer_defines_inspect_container():
    """The verb lives in the adapter now; log_shipper must not re-export it."""
    import lablink_cli.log_shipper as ls

    assert not hasattr(ls, "inspect_container")


def test_container_status_running_moved_from_log_shipper():
    # Ported from log_shipper.TestInspectContainer.test_running (Task 2) —
    # same scenario as test_container_status_maps_running above, kept as a
    # separate case per the task's "do not delete coverage" instruction.
    with patch(
        "lablink_cli.docker.subprocess.run",
        return_value=_completed(0, stdout="running\n", stderr=""),
    ):
        assert Docker().container_status("lablink-client") == "running"


def test_container_status_missing_moved_from_log_shipper():
    # Ported from log_shipper.TestInspectContainer.test_missing_returns_missing.
    with patch(
        "lablink_cli.docker.subprocess.run",
        return_value=_completed(
            1, stdout="", stderr="Error: No such object: lablink-client\n"
        ),
    ):
        assert Docker().container_status("lablink-client") == "missing"


def test_container_status_maps_exited():
    with patch(
        "lablink_cli.docker.subprocess.run",
        return_value=_completed(0, stdout="exited\n"),
    ):
        assert Docker().container_status("c") == "exited"


def test_container_status_maps_restarting():
    with patch(
        "lablink_cli.docker.subprocess.run",
        return_value=_completed(0, stdout="restarting\n"),
    ):
        assert Docker().container_status("c") == "restarting"


def test_container_status_daemon_error_on_other_nonzero_stderr():
    with patch(
        "lablink_cli.docker.subprocess.run",
        return_value=_completed(
            1, stderr="Cannot connect to the Docker daemon\n"
        ),
    ):
        assert Docker().container_status("c") == "daemon_error"
