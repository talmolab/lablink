"""Tests for lablink_cli.commands.logs SSH helpers."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from lablink_cli.commands.logs import (
    _ssh_via_instance_connect,
    _ssh_via_private_key,
)


class TestSshViaInstanceConnect:
    @patch("lablink_cli.commands.logs.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="log output"
        )
        result = _ssh_via_instance_connect(
            "i-123", "us-east-1", "echo hello"
        )
        assert result == "log output"
        mock_run.assert_called_once()

    @patch("lablink_cli.commands.logs.subprocess.run")
    def test_nonzero_exit_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error"
        )
        result = _ssh_via_instance_connect(
            "i-123", "us-east-1", "echo hello"
        )
        assert result is None

    @patch("lablink_cli.commands.logs.subprocess.run")
    def test_timeout_returns_none(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="ssh", timeout=30
        )
        result = _ssh_via_instance_connect(
            "i-123", "us-east-1", "echo hello"
        )
        assert result is None

    @patch("lablink_cli.commands.logs.subprocess.run")
    def test_file_not_found_returns_none(self, mock_run):
        mock_run.side_effect = FileNotFoundError("aws not found")
        result = _ssh_via_instance_connect(
            "i-123", "us-east-1", "echo hello"
        )
        assert result is None


class TestSshViaPrivateKey:
    @patch("lablink_cli.commands.logs.subprocess.run")
    @patch("lablink_cli.commands.logs.get_terraform_outputs")
    def test_success(self, mock_outputs, mock_run, tmp_path):
        mock_outputs.return_value = {
            "private_key_pem": "-----BEGIN RSA PRIVATE KEY-----\n"
            "fake\n"
            "-----END RSA PRIVATE KEY-----"
        }
        mock_run.return_value = MagicMock(
            returncode=0, stdout="log output"
        )
        result = _ssh_via_private_key(
            "1.2.3.4", "echo hello", tmp_path
        )
        assert result == "log output"

    @patch("lablink_cli.commands.logs.get_terraform_outputs")
    def test_no_private_key_returns_none(self, mock_outputs, tmp_path):
        mock_outputs.return_value = {}
        result = _ssh_via_private_key(
            "1.2.3.4", "echo hello", tmp_path
        )
        assert result is None

    def test_no_ip_returns_none(self, tmp_path):
        result = _ssh_via_private_key(
            "\u2014", "echo hello", tmp_path
        )
        assert result is None

    @patch("lablink_cli.commands.logs.subprocess.run")
    @patch("lablink_cli.commands.logs.get_terraform_outputs")
    def test_nonzero_exit_returns_stderr(self, mock_outputs, mock_run, tmp_path):
        mock_outputs.return_value = {
            "private_key_pem": "-----BEGIN RSA PRIVATE KEY-----\n"
            "fake\n"
            "-----END RSA PRIVATE KEY-----"
        }
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="connection refused"
        )
        result = _ssh_via_private_key(
            "1.2.3.4", "echo hello", tmp_path
        )
        assert "connection refused" in result

    @patch("lablink_cli.commands.logs.subprocess.run")
    @patch("lablink_cli.commands.logs.get_terraform_outputs")
    def test_timeout_returns_none(self, mock_outputs, mock_run, tmp_path):
        mock_outputs.return_value = {
            "private_key_pem": "-----BEGIN RSA PRIVATE KEY-----\n"
            "fake\n"
            "-----END RSA PRIVATE KEY-----"
        }
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="ssh", timeout=30
        )
        result = _ssh_via_private_key(
            "1.2.3.4", "echo hello", tmp_path
        )
        assert result is None
