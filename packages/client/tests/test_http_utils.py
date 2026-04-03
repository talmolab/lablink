"""Tests for shared HTTP utilities."""

from unittest.mock import MagicMock

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
        monkeypatch.setenv("API_TOKEN", "tok123")
        monkeypatch.setenv("VM_NAME", "vm-1")

        cfg = MagicMock()
        base_url, api_token, vm_name = get_client_env(cfg)

        assert base_url == "https://example.com"
        assert api_token == "tok123"
        assert vm_name == "vm-1"

    def test_fallback_to_config(self, monkeypatch):
        monkeypatch.delenv("ALLOCATOR_URL", raising=False)
        monkeypatch.delenv("API_TOKEN", raising=False)
        monkeypatch.delenv("VM_NAME", raising=False)

        cfg = MagicMock()
        cfg.allocator.host = "localhost"
        cfg.allocator.port = 5000

        base_url, api_token, vm_name = get_client_env(cfg)

        assert base_url == "http://localhost:5000"
        assert api_token == ""
        assert vm_name is None
