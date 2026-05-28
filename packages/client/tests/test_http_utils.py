"""Tests for shared HTTP utilities."""

import importlib
from unittest.mock import MagicMock

import pytest

from lablink_client_service.http_utils import (
    get_auth_headers,
    get_client_env,
    sanitize_url,
)


class TestSanitizeUrl:
    def test_trailing_slash(self):
        assert sanitize_url("http://example.com/") == "http://example.com"

    def test_dot_after_scheme(self):
        assert sanitize_url("http://.example.com") == "http://example.com"

    def test_https_dot_after_scheme(self):
        assert sanitize_url("https://.lablink.sleap.ai") == "https://lablink.sleap.ai"

    def test_leading_dot_no_scheme(self):
        assert sanitize_url(".lablink.sleap.ai") == "lablink.sleap.ai"

    def test_clean_url_unchanged(self):
        assert sanitize_url("https://example.com") == "https://example.com"

    def test_trailing_slash_and_dot(self):
        assert sanitize_url("http://.example.com/") == "http://example.com"


class TestGetAuthHeaders:
    def test_with_token(self):
        headers = get_auth_headers("my-token")
        assert headers == {"Authorization": "Bearer my-token"}

    def test_empty_token(self):
        assert get_auth_headers("") == {}

    def test_no_token(self):
        assert get_auth_headers() == {}


class TestGetClientEnv:
    def test_from_env_vars(self, monkeypatch):
        monkeypatch.setenv("ALLOCATOR_URL", "https://.example.com/")
        monkeypatch.setenv("CLIENT_SECRET", "tok123")
        monkeypatch.setenv("VM_NAME", "vm-1")

        cfg = MagicMock()
        base_url, api_token, vm_name = get_client_env(cfg)

        assert base_url == "https://example.com"
        assert api_token == "tok123"
        assert vm_name == "vm-1"

    def test_fallback_to_config_url(self, monkeypatch):
        monkeypatch.delenv("ALLOCATOR_URL", raising=False)
        monkeypatch.setenv("CLIENT_SECRET", "tok123")
        monkeypatch.delenv("VM_NAME", raising=False)

        cfg = MagicMock()
        cfg.allocator.host = "localhost"
        cfg.allocator.port = 5000

        base_url, api_token, vm_name = get_client_env(cfg)

        assert base_url == "http://localhost:5000"
        assert api_token == "tok123"
        assert vm_name is None


def test_get_client_env_uses_client_secret(monkeypatch):
    from lablink_client_service import http_utils
    importlib.reload(http_utils)

    class _Cfg:
        class allocator:
            host = "h"
            port = 5000

    monkeypatch.setenv("ALLOCATOR_URL", "http://a:5000")
    monkeypatch.setenv("CLIENT_SECRET", "new-client-secret")
    monkeypatch.setenv("VM_NAME", "vm-1")

    base_url, token, vm = http_utils.get_client_env(_Cfg)
    assert token == "new-client-secret"
    assert vm == "vm-1"


def test_get_client_env_raises_when_client_secret_missing(monkeypatch):
    """After PR D4, CLIENT_SECRET is mandatory — no API_TOKEN fallback."""
    monkeypatch.delenv("CLIENT_SECRET", raising=False)
    monkeypatch.delenv("API_TOKEN", raising=False)
    from lablink_client_service.http_utils import get_client_env

    cfg = MagicMock()
    cfg.allocator.host = "localhost"
    cfg.allocator.port = 5000

    with pytest.raises(RuntimeError, match="CLIENT_SECRET"):
        get_client_env(cfg)
