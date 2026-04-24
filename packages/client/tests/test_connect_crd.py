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


CRD_COMMAND_WITH_CODE = "DISPLAY= /opt/google/chrome-remote-desktop/start-host " \
    "--code='hidden_code' " \
    "--redirect-url='https://remotedesktop.google.com/_/oauthredirect' " \
    "--name=$(hostname)"


def test_construct_command_with_code():
    args = argparse.Namespace(code="test_code")
    with patch.dict(os.environ, {"VM_NAME": "test_vm"}):
        command = construct_command(args)

    expected = "DISPLAY= /opt/google/chrome-remote-desktop/start-host " \
                "--code=test_code " \
                "--redirect-url='https://remotedesktop.google.com/_/oauthredirect' " \
                "--name=test_vm"
    assert command == expected


def test_construct_command_without_vm_name():
    args = argparse.Namespace(code="test_code")
    with patch.dict(os.environ, {}, clear=True):
        command = construct_command(args)

    expected = "DISPLAY= /opt/google/chrome-remote-desktop/start-host " \
                "--code=test_code " \
                "--redirect-url='https://remotedesktop.google.com/_/oauthredirect' " \
                "--name=$(hostname)"
    assert command == expected


def test_construct_command_without_code():
    args = argparse.Namespace(code=None)
    with pytest.raises(
        ValueError, match="Code must be provided to construct the command."
    ):
        construct_command(args)


@patch("lablink_client_service.connect_crd.construct_command")
@patch("lablink_client_service.connect_crd.create_parser")
def test_reconstruct_command(mock_create_parser, mock_construct_command):
    mock_parser = MagicMock()
    mock_args = argparse.Namespace(code="test_code")
    mock_parser.parse_known_args.return_value = (mock_args, [])
    mock_create_parser.return_value = mock_parser
    mock_construct_command.return_value = "test_command"

    result = reconstruct_command(
        "DISPLAY= /opt/google/chrome-remote-desktop/start-host " \
        "--code=test_code " \
        "--redirect-url='https://remotedesktop.google.com/_/oauthredirect' " \
        "--name=test_vm"
    )

    mock_create_parser.assert_called_once()
    mock_parser.parse_known_args.assert_called_once_with(
        args=[
            "DISPLAY=",
            "/opt/google/chrome-remote-desktop/start-host",
            "--code=test_code",
            "--redirect-url='https://remotedesktop.google.com/_/oauthredirect'",
            "--name=test_vm",
        ]
    )
    mock_construct_command.assert_called_once_with(mock_args)
    assert result == "test_command"


def test_whole_reconstruction():
    crd_command = CRD_COMMAND_WITH_CODE
    command = reconstruct_command(crd_command)
    assert command == crd_command


@patch("lablink_client_service.connect_crd.is_crd_registered", return_value=False)
@patch("lablink_client_service.connect_crd.subprocess.run")
@patch("lablink_client_service.connect_crd.reconstruct_command")
def test_connect_to_crd(
    mock_reconstruct_command, mock_subprocess_run, mock_is_registered
):
    input_command = CRD_COMMAND_WITH_CODE
    reconstructed_command = CRD_COMMAND_WITH_CODE

    mock_reconstruct_command.return_value = reconstructed_command
    pin = "123456"
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "Connection successful"
    mock_result.stderr = ""
    mock_subprocess_run.return_value = mock_result

    connect_to_crd(input_command, pin)

    mock_reconstruct_command.assert_called_once_with(input_command)
    mock_subprocess_run.assert_called_once_with(
        input_command,
        input="123456\n123456\n",
        shell=True,
        capture_output=True,
        text=True,
    )


@patch("lablink_client_service.connect_crd.is_crd_registered", return_value=False)
@patch("lablink_client_service.connect_crd.subprocess.run")
def test_whole_connection_workflow(mock_subprocess_run, mock_is_registered):
    input_command = CRD_COMMAND_WITH_CODE
    pin = "123456"
    mock_subprocess_run.return_value = MagicMock(
        returncode=0, stdout="", stderr=""
    )

    with patch.dict(os.environ, {"VM_NAME": "test_vm"}):
        connect_to_crd(input_command, pin)

    expected_command = "DISPLAY= /opt/google/chrome-remote-desktop/start-host " \
    "--code='hidden_code' " \
    "--redirect-url='https://remotedesktop.google.com/_/oauthredirect' " \
    "--name=test_vm"
    mock_subprocess_run.assert_called_once_with(
        expected_command,
        input="123456\n123456\n",
        shell=True,
        capture_output=True,
        text=True,
    )


@patch("lablink_client_service.connect_crd.start_crd_daemon")
@patch("lablink_client_service.connect_crd.is_crd_registered", return_value=True)
@patch("lablink_client_service.connect_crd.subprocess.run")
def test_connect_to_crd_starts_daemon_when_host_registered_despite_nonzero_exit(
    mock_subprocess_run, mock_is_registered, mock_start_daemon
):
    """start-host returns non-zero in Docker because systemctl can't
    run, but host registration still succeeded (config file written).
    In that case connect_to_crd should start the daemon itself via
    user-session instead of surfacing an error."""
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
