"""Tests for lablink_cli.commands.launch client VM launching."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lablink_cli.api import (
    AllocatorAuthError,
    AllocatorError,
    AllocatorUnavailableError,
)
from lablink_cli.commands.launch import run_launch


class TestRunLaunch:
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_no_allocator_url(self, mock_url, mock_creds, mock_cfg):
        mock_url.return_value = ""

        with pytest.raises(SystemExit):
            run_launch(mock_cfg, num_vms=1)

    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_successful_launch(
        self, mock_url, mock_creds, mock_api_cls, mock_cfg
    ):
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_api = MagicMock()
        mock_api.launch_vms.return_value = {
            "status": "success", "output": "Created 2 VMs",
        }
        mock_api_cls.return_value = mock_api

        # Should not raise
        run_launch(mock_cfg, num_vms=2)

        mock_api_cls.assert_called_once_with(
            "http://1.2.3.4", "admin", "password", mock_cfg.ssl.provider
        )
        mock_api.launch_vms.assert_called_once_with(2)

    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_auth_failure(self, mock_url, mock_creds, mock_api_cls, mock_cfg):
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "wrong")
        mock_api = MagicMock()
        mock_api.launch_vms.side_effect = AllocatorAuthError(
            "Authentication failed"
        )
        mock_api_cls.return_value = mock_api

        with pytest.raises(SystemExit):
            run_launch(mock_cfg, num_vms=1)

    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_connection_error(
        self, mock_url, mock_creds, mock_api_cls, mock_cfg
    ):
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_api = MagicMock()
        mock_api.launch_vms.side_effect = AllocatorUnavailableError(
            "connection refused"
        )
        mock_api_cls.return_value = mock_api

        with pytest.raises(SystemExit):
            run_launch(mock_cfg, num_vms=1)

    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_self_signed_ssl(
        self, mock_url, mock_creds, mock_api_cls, mock_cfg
    ):
        mock_url.return_value = "https://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_cfg.ssl.provider = "self_signed"
        mock_api = MagicMock()
        mock_api.launch_vms.return_value = {"status": "success", "output": ""}
        mock_api_cls.return_value = mock_api

        run_launch(mock_cfg, num_vms=1)

        mock_api_cls.assert_called_once_with(
            "https://1.2.3.4", "admin", "password", "self_signed"
        )

    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_http_server_error(
        self, mock_url, mock_creds, mock_api_cls, mock_cfg
    ):
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_api = MagicMock()
        mock_api.launch_vms.side_effect = AllocatorError(
            "HTTP 500: out of capacity"
        )
        mock_api_cls.return_value = mock_api

        with pytest.raises(SystemExit):
            run_launch(mock_cfg, num_vms=1)


class TestManualLaunchNoOp:
    def test_manual_provider_prints_explanation_and_exits_zero(
        self, capsys, mock_cfg,
    ):
        mock_cfg.provider = "manual"
        # Should NOT raise and NOT touch AWS
        run_launch(mock_cfg, num_vms=5, verbose=False)
        out = capsys.readouterr().out
        assert "Manual provider" in out
        assert "lablink client register" in " ".join(out.split())

    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_manual_provider_does_not_touch_allocator(
        self, mock_url, mock_creds, mock_api_cls, mock_cfg,
    ):
        mock_cfg.provider = "manual"
        run_launch(mock_cfg, num_vms=3, verbose=False)
        mock_url.assert_not_called()
        mock_creds.assert_not_called()
        mock_api_cls.assert_not_called()
