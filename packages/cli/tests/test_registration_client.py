"""Tests for lablink_cli.api.RegistrationClient."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from lablink_cli.api import (
    AllocatorAuthError,
    AllocatorConflictError,
    AllocatorError,
    AllocatorUnavailableError,
    RegistrationClient,
)


def _make_client(
    base_url: str = "https://lablink.example.com",
    register_token: str = "test-token",
    ssl_provider: str = "none",
) -> RegistrationClient:
    return RegistrationClient(
        base_url, register_token, ssl_provider=ssl_provider
    )


def _payload() -> dict:
    return {
        "hostname": "byo-gpu-01",
        "machine_identity": "abc123",
        "lan_ip": "192.168.1.42",
        "gpu_present": True,
        "gpu_model": "NVIDIA T4",
    }


class TestRegister:
    @patch("lablink_cli.api.urlopen")
    def test_success_posts_bearer_and_body(self, mock_urlopen):
        response = {
            "client_id": 42,
            "client_secret": "s",
            "agent_token": "a",
            "register_token": "r",
            "allocator_url": "https://lablink.example.com",
            "connectivity": "lan_direct",
            "client_image": "ghcr.io/talmolab/lablink-client:0.4.0",
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = _make_client().register(**_payload())

        assert result == response
        req = mock_urlopen.call_args[0][0]
        assert req.full_url == "https://lablink.example.com/api/v1/clients/register"
        assert req.method == "POST"
        assert req.get_header("Authorization") == "Bearer test-token"
        body = json.loads(req.data.decode())
        assert body["hostname"] == "byo-gpu-01"
        assert body["machine_identity"] == "abc123"
        assert body["provider"] == "manual"
        assert body["endpoint_url"] == "http://192.168.1.42:7070"
        assert body["provider_metadata"] == {"lan_ip": "192.168.1.42"}
        assert body["gpu_present"] is True
        assert body["gpu_model"] == "NVIDIA T4"

    @patch("lablink_cli.api.urlopen")
    def test_401_raises_auth_error(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            "url", 401, "Unauthorized", {},
            MagicMock(read=lambda: b'{"error":"registration rejected"}'),
        )
        with pytest.raises(AllocatorAuthError) as exc:
            _make_client().register(**_payload())
        assert "stale" in str(exc.value)

    @patch("lablink_cli.api.urlopen")
    def test_409_raises_conflict(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            "url", 409, "Conflict", {},
            MagicMock(read=lambda: b'{"error":"registration conflict"}'),
        )
        with pytest.raises(AllocatorConflictError):
            _make_client().register(**_payload())

    @patch("lablink_cli.api.urlopen")
    def test_400_raises_with_server_message(self, mock_urlopen):
        mock_urlopen.side_effect = HTTPError(
            "url", 400, "Bad Request", {},
            MagicMock(read=lambda: b'{"error":"hostname required"}'),
        )
        with pytest.raises(AllocatorError) as exc:
            _make_client().register(**_payload())
        assert "hostname required" in str(exc.value)

    @patch("lablink_cli.api.urlopen")
    def test_connection_refused_raises_unavailable(self, mock_urlopen):
        mock_urlopen.side_effect = URLError("Connection refused")
        with pytest.raises(AllocatorUnavailableError):
            _make_client().register(**_payload())

    @patch("lablink_cli.api.urlopen")
    def test_non_json_response_raises(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"<html>500</html>"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        with pytest.raises(AllocatorError):
            _make_client().register(**_payload())


class TestSslProvider:
    def test_default_strict_tls(self):
        client = _make_client(ssl_provider="none")
        assert client._ssl_ctx.verify_mode != 0  # not CERT_NONE
        assert client._ssl_ctx.check_hostname is True

    def test_self_signed_tolerant(self):
        import ssl as _ssl
        client = _make_client(ssl_provider="self_signed")
        assert client._ssl_ctx.verify_mode == _ssl.CERT_NONE
        assert client._ssl_ctx.check_hostname is False
