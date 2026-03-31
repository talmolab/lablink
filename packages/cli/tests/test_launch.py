"""Tests for lablink_cli.commands.launch client VM launching."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from lablink_cli.commands.launch import run_launch


class TestRunLaunch:
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_no_allocator_url(self, mock_url, mock_creds, mock_cfg):
        mock_url.return_value = ""

        with pytest.raises(SystemExit):
            run_launch(mock_cfg, num_vms=1)

    @patch("lablink_cli.commands.launch.urlopen")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_successful_launch(self, mock_url, mock_creds, mock_urlopen, mock_cfg):
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"status": "success", "output": "Created 2 VMs"}
        ).encode()
        mock_urlopen.return_value = mock_resp

        # Should not raise
        run_launch(mock_cfg, num_vms=2)

        # Verify the request was made to the correct URL
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert "/api/launch" in req.full_url

    @patch("lablink_cli.commands.launch.urlopen")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_auth_failure(self, mock_url, mock_creds, mock_urlopen, mock_cfg):
        from urllib.error import HTTPError

        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "wrong")

        mock_urlopen.side_effect = HTTPError(
            "http://1.2.3.4/api/launch", 401, "Unauthorized", {}, None
        )

        with pytest.raises(SystemExit):
            run_launch(mock_cfg, num_vms=1)

    @patch("lablink_cli.commands.launch.urlopen")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_connection_error(self, mock_url, mock_creds, mock_urlopen, mock_cfg):
        from urllib.error import URLError

        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_urlopen.side_effect = URLError("connection refused")

        with pytest.raises(SystemExit):
            run_launch(mock_cfg, num_vms=1)

    @patch("lablink_cli.commands.launch.urlopen")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_self_signed_ssl(self, mock_url, mock_creds, mock_urlopen, mock_cfg):
        mock_url.return_value = "https://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_cfg.ssl.provider = "self_signed"

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"status": "success"}
        ).encode()
        mock_urlopen.return_value = mock_resp

        run_launch(mock_cfg, num_vms=1)

        # Verify SSL context was created (urlopen called with context kwarg)
        call_kwargs = mock_urlopen.call_args[1]
        assert "context" in call_kwargs

    @patch("lablink_cli.commands.launch.urlopen")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_http_server_error(self, mock_url, mock_creds, mock_urlopen, mock_cfg):
        from io import BytesIO
        from urllib.error import HTTPError

        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")

        error_body = BytesIO(json.dumps({"error": "out of capacity"}).encode())
        mock_urlopen.side_effect = HTTPError(
            "http://1.2.3.4/api/launch", 500, "Internal Server Error",
            {}, error_body
        )

        with pytest.raises(SystemExit):
            run_launch(mock_cfg, num_vms=1)
