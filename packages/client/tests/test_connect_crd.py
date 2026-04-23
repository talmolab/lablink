import argparse
import os

import pytest
from unittest.mock import patch, MagicMock

from lablink_client_service import connect_crd
from lablink_client_service.connect_crd import (
    construct_command,
    reconstruct_command,
    connect_to_crd,
    is_crd_registered,
    start_crd_daemon,
)


CRD_COMMAND_WITH_CODE = (
    "/opt/google/chrome-remote-desktop/start-host "
    "--code=hidden_code "
    "--redirect-url=https://remotedesktop.google.com/_/oauthredirect "
    "--name=$(hostname)"
)

EXPECTED_ARGV = [
    "/opt/google/chrome-remote-desktop/start-host",
    "--code=hidden_code",
    "--redirect-url=https://remotedesktop.google.com/_/oauthredirect",
    "--name=test_vm",
]


def test_construct_command_with_code():
    args = argparse.Namespace(code="test_code")
    with patch.dict(os.environ, {"VM_NAME": "test_vm"}):
        command = construct_command(args)

    assert command == [
        "/opt/google/chrome-remote-desktop/start-host",
        "--code=test_code",
        "--redirect-url=https://remotedesktop.google.com/_/oauthredirect",
        "--name=test_vm",
    ]


def test_construct_command_without_vm_name():
    args = argparse.Namespace(code="test_code")
    with patch.dict(os.environ, {}, clear=True):
        with patch(
            "lablink_client_service.connect_crd.socket.gethostname",
            return_value="fallback-host",
        ):
            command = construct_command(args)

    assert command == [
        "/opt/google/chrome-remote-desktop/start-host",
        "--code=test_code",
        "--redirect-url=https://remotedesktop.google.com/_/oauthredirect",
        "--name=fallback-host",
    ]


def test_construct_command_without_code():
    args = argparse.Namespace(code=None)
    with pytest.raises(
        ValueError, match="Code must be provided to construct the command."
    ):
        construct_command(args)


@pytest.mark.parametrize(
    "good_code,expected_arg",
    [
        ("4/abc123", "--code=4/abc123"),
        ("test_code", "--code=test_code"),
        ("4/0Aerz0j_I9c7gCgYIARAA-GBASNwF", "--code=4/0Aerz0j_I9c7gCgYIARAA-GBASNwF"),
        ("a-b_c/d", "--code=a-b_c/d"),
        # Google's copy-pasteable command wraps the code in double
        # quotes; we strip a single matched pair.
        ('"4/abc123"', "--code=4/abc123"),
        ("'4/abc123'", "--code=4/abc123"),
    ],
)
def test_construct_command_accepts_legitimate_codes(good_code, expected_arg):
    args = argparse.Namespace(code=good_code)
    with patch.dict(os.environ, {"VM_NAME": "vm-1"}):
        argv = construct_command(args)
    assert argv[1] == expected_arg


def test_construct_command_passes_metacharacters_as_literal_argv():
    """With shell=False, a stray metacharacter in the code is passed
    as a literal arg to start-host — no shell interprets it. This is
    the security-critical property; validation is the allocator's job.
    """
    args = argparse.Namespace(code="x;id")
    with patch.dict(os.environ, {"VM_NAME": "vm-1"}):
        argv = construct_command(args)
    assert argv[1] == "--code=x;id"  # literal, not a shell statement


def test_reconstruct_command_returns_list_argv():
    with patch.dict(os.environ, {"VM_NAME": "test_vm"}):
        argv = reconstruct_command(CRD_COMMAND_WITH_CODE)
    assert argv == EXPECTED_ARGV


@patch("lablink_client_service.connect_crd.is_crd_registered", return_value=False)
@patch("lablink_client_service.connect_crd.subprocess.run")
@patch("lablink_client_service.connect_crd.reconstruct_command")
def test_connect_to_crd(
    mock_reconstruct_command, mock_subprocess_run, mock_is_registered
):
    mock_reconstruct_command.return_value = list(EXPECTED_ARGV)
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stderr = ""
    mock_subprocess_run.return_value = mock_result

    connect_to_crd(CRD_COMMAND_WITH_CODE, "123456")

    mock_reconstruct_command.assert_called_once_with(CRD_COMMAND_WITH_CODE)
    call = mock_subprocess_run.call_args
    assert call.args[0] == EXPECTED_ARGV
    assert call.kwargs["shell"] is False
    assert call.kwargs["input"] == "123456\n123456\n"
    assert call.kwargs["capture_output"] is True
    assert call.kwargs["text"] is True
    assert call.kwargs["env"]["DISPLAY"] == ""


@patch("lablink_client_service.connect_crd.is_crd_registered", return_value=False)
@patch("lablink_client_service.connect_crd.subprocess.run")
def test_whole_connection_workflow(mock_subprocess_run, mock_is_registered):
    mock_subprocess_run.return_value = MagicMock(returncode=0, stderr="")

    with patch.dict(os.environ, {"VM_NAME": "test_vm"}):
        connect_to_crd(CRD_COMMAND_WITH_CODE, "123456")

    call = mock_subprocess_run.call_args
    assert call.args[0] == EXPECTED_ARGV
    assert call.kwargs["shell"] is False
    assert call.kwargs["input"] == "123456\n123456\n"
    assert call.kwargs["env"]["DISPLAY"] == ""


@patch("lablink_client_service.connect_crd.start_crd_daemon")
@patch("lablink_client_service.connect_crd.is_crd_registered", return_value=True)
@patch("lablink_client_service.connect_crd.subprocess.run")
def test_connect_to_crd_starts_daemon_when_host_registered_despite_nonzero_exit(
    mock_subprocess_run, mock_is_registered, mock_start_daemon
):
    """start-host returns non-zero in Docker because systemctl can't
    run, but host registration still succeeded (config file written).
    In that case connect_to_crd should start the daemon itself via
    start_crd_daemon() instead of surfacing an error."""
    mock_subprocess_run.return_value = MagicMock(
        returncode=1, stdout="", stderr="Failed to start host."
    )
    with patch.dict(os.environ, {"VM_NAME": "test_vm"}):
        connect_to_crd(CRD_COMMAND_WITH_CODE, "123456")
    mock_is_registered.assert_called_once()
    mock_start_daemon.assert_called_once()


def test_set_logger():
    """Test that the logger can be set."""
    mock_logger = MagicMock()
    connect_crd.set_logger(mock_logger)
    assert connect_crd.logger is mock_logger


@patch("lablink_client_service.connect_crd.logging.shutdown")
@patch("lablink_client_service.connect_crd.time.sleep")
def test_cleanup_logs(mock_sleep, mock_shutdown):
    """Test that logs are cleaned up properly."""
    mock_handler = MagicMock()
    mock_handler.flush = MagicMock()

    with patch.object(connect_crd, "logger") as mock_logger:
        mock_logger.handlers = [mock_handler]
        connect_crd.cleanup_logs()
        mock_handler.flush.assert_called_once()
        mock_sleep.assert_called_once_with(1.5)
        mock_shutdown.assert_called_once()


@patch("lablink_client_service.connect_crd.logging.shutdown")
@patch("lablink_client_service.connect_crd.time.sleep")
def test_cleanup_logs_exception(mock_sleep, mock_shutdown):
    """Test that an exception during log cleanup is handled."""
    mock_handler = MagicMock()
    mock_handler.flush.side_effect = Exception("test error")

    with patch.object(connect_crd, "logger") as mock_logger:
        mock_logger.handlers = [mock_handler]
        mock_logger.error = MagicMock()
        connect_crd.cleanup_logs()
        mock_logger.error.assert_called_once()
        mock_sleep.assert_not_called()


@patch("lablink_client_service.connect_crd.glob.glob")
def test_is_crd_registered_true(mock_glob):
    """Registered when a host#<hash>.json exists."""
    mock_glob.return_value = [
        "/home/client/.config/chrome-remote-desktop/host#abc.json"
    ]
    assert is_crd_registered() is True
    mock_glob.assert_called_once_with(
        "/home/client/.config/chrome-remote-desktop/host#*.json"
    )


@patch("lablink_client_service.connect_crd.glob.glob")
def test_is_crd_registered_false(mock_glob):
    """Not registered when no host config files are present."""
    mock_glob.return_value = []
    assert is_crd_registered() is False


@patch("lablink_client_service.connect_crd.subprocess.run")
@patch("lablink_client_service.connect_crd.glob.glob")
def test_start_crd_daemon_success(mock_glob, mock_run):
    """Daemon start invokes chrome-remote-desktop --start --new-session,
    matching the ExecStart in /lib/systemd/system/chrome-remote-desktop@.service.
    """
    config_path = "/home/client/.config/chrome-remote-desktop/host#abc.json"
    mock_glob.return_value = [config_path]
    mock_run.return_value = MagicMock(returncode=0, stderr="")

    start_crd_daemon()

    call = mock_run.call_args
    assert call.args[0] == (
        "/opt/google/chrome-remote-desktop/chrome-remote-desktop "
        "--start --new-session"
    )
    assert call.kwargs["shell"] is True
    assert call.kwargs["timeout"] == 30
    assert call.kwargs["env"]["XDG_SESSION_CLASS"] == "user"
    assert call.kwargs["env"]["XDG_SESSION_TYPE"] == "x11"


@patch("lablink_client_service.connect_crd.subprocess.run")
@patch("lablink_client_service.connect_crd.glob.glob")
def test_start_crd_daemon_no_config(mock_glob, mock_run):
    """Logs an error and skips subprocess when no host config is found."""
    mock_glob.return_value = []

    start_crd_daemon()

    mock_run.assert_not_called()


@patch("lablink_client_service.connect_crd.subprocess.run")
@patch("lablink_client_service.connect_crd.glob.glob")
def test_start_crd_daemon_failure(mock_glob, mock_run):
    """Non-zero exit is logged but does not raise."""
    mock_glob.return_value = [
        "/home/client/.config/chrome-remote-desktop/host#abc.json"
    ]
    mock_run.return_value = MagicMock(returncode=1, stderr="oops")

    # Should not raise
    start_crd_daemon()
    mock_run.assert_called_once()


@patch("lablink_client_service.connect_crd.subprocess.run")
@patch("lablink_client_service.connect_crd.glob.glob")
def test_start_crd_daemon_timeout(mock_glob, mock_run):
    """TimeoutExpired is caught, logged, and swallowed.

    Without this, a hanging daemon start would block the subscribe
    loop forever and prevent any subsequent CRD reassignment.
    """
    import subprocess

    mock_glob.return_value = [
        "/home/client/.config/chrome-remote-desktop/host#abc.json"
    ]
    mock_run.side_effect = subprocess.TimeoutExpired(
        cmd="chrome-remote-desktop --start", timeout=30
    )

    # Should not raise
    start_crd_daemon()
    mock_run.assert_called_once()
