import argparse
import os

import pytest
from unittest.mock import patch, MagicMock

from lablink_client.connect_crd import (
    construct_command,
    reconstruct_command,
    connect_to_crd,
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


@patch("lablink_client.connect_crd.construct_command")
@patch("lablink_client.connect_crd.create_parser")
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


@patch("lablink_client.connect_crd.subprocess.run")
@patch("lablink_client.connect_crd.reconstruct_command")
def test_connect_to_crd(mock_reconstruct_command, mock_subprocess_run):
    input_command = CRD_COMMAND_WITH_CODE
    reconstructed_command = CRD_COMMAND_WITH_CODE

    mock_reconstruct_command.return_value = reconstructed_command
    pin = "123456"
    mock_result = MagicMock()
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


@patch("lablink_client.connect_crd.subprocess.run")
def test_whole_connection_workflow(mock_subprocess_run):
    input_command = CRD_COMMAND_WITH_CODE
    pin = "123456"

    with patch.dict(os.environ, {"VM_NAME": "test_vm"}):
        connect_to_crd(input_command, pin)

    expected_command = "DISPLAY= /opt/google/chrome-remote-desktop/start-host " \
    "--code='hidden_code' " \
    "--redirect-url='https://remotedesktop.google.com/_/oauthredirect' --name=test_vm"
    mock_subprocess_run.assert_called_once_with(
        expected_command,
        input="123456\n123456\n",
        shell=True,
        capture_output=True,
        text=True,
    )
