"""Tests for lablink_cli.api AllocatorAPI."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from lablink_cli.api import (
    AllocatorAPI,
    AllocatorAuthError,
    AllocatorError,
    AllocatorNotFoundError,
    AllocatorUnavailableError,
)


def _make_api(
    base_url: str = "https://allocator.example.com",
    admin_user: str = "admin",
    admin_password: str = "secret",
    ssl_provider: str = "none",
) -> AllocatorAPI:
    return AllocatorAPI(base_url, admin_user, admin_password, ssl_provider)


class TestDestroyVms:
    @patch("lablink_cli.api.urlopen")
    def test_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"status": "ok"}
        ).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        api = _make_api()
        result = api.destroy_vms()

        assert result["status"] == "ok"
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        assert req.full_url == "https://allocator.example.com/destroy"
        assert req.method == "POST"
        assert "Basic" in req.get_header("Authorization")

    @patch("lablink_cli.api.urlopen")
    def test_401_raises_auth_error(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            "url", 401, "Unauthorized", {}, None
        )
        api = _make_api()
        with pytest.raises(AllocatorAuthError):
            api.destroy_vms()

    @patch("lablink_cli.api.urlopen")
    def test_404_raises_not_found(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            "url", 404, "Not Found", {}, None
        )
        api = _make_api()
        with pytest.raises(AllocatorNotFoundError):
            api.destroy_vms()

    @patch("lablink_cli.api.urlopen")
    def test_502_raises_unavailable(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            "url", 502, "Bad Gateway", {}, None
        )
        api = _make_api()
        with pytest.raises(AllocatorUnavailableError):
            api.destroy_vms()

    @patch("lablink_cli.api.urlopen")
    def test_connection_error_raises_unavailable(self, mock_urlopen):
        mock_urlopen.side_effect = URLError("connection refused")
        api = _make_api()
        with pytest.raises(AllocatorUnavailableError):
            api.destroy_vms()

    @patch("lablink_cli.api.urlopen")
    def test_error_status_in_body_raises(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"status": "error", "error": "terraform failed"}
        ).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        api = _make_api()
        with pytest.raises(AllocatorError, match="terraform failed"):
            api.destroy_vms()

    @patch("lablink_cli.api.urlopen")
    def test_other_http_error_raises_allocator_error(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            "url", 500, "Internal Server Error", {}, None
        )
        api = _make_api()
        with pytest.raises(AllocatorError):
            api.destroy_vms()

    @patch("lablink_cli.api.urlopen")
    def test_self_signed_ssl(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        api = _make_api(ssl_provider="self_signed")
        api.destroy_vms()

        mock_urlopen.assert_called_once()
