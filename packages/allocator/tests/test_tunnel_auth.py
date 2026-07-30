"""Tests for GET/POST /internal/tunnel_auth -- the nginx auth_request gate
for the reverse-tunnel WebSocket attach point.

Security model under test: nginx captures the client's prefix from the
FIRST path segment and hands it to this endpoint as its own header
(X-Tunnel-Prefix) -- the endpoint must not re-derive identity from the
URI itself, since the client's real request path is /<prefix>/events and
last-segment extraction would read "events" and 401 every legitimate
attach. The bearer token authenticates the identity nginx already
resolved. Missing header, unknown prefix, absent secret hash, a
scheme-less token, or a mismatched secret must all fail closed (401)
before any per-client state is touched.

Tests pin WHICH identity was resolved and whose hash was checked
(assert_called_once_with), not just the final status code -- a MagicMock
that ignores its arguments would otherwise hide an extraction bug like
the one that made this endpoint 401 every real attach.
"""
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def tunnel_auth_client(app, monkeypatch):
    """Flask test client wired for /internal/tunnel_auth, with a MagicMock
    database. Returns (test_client, fake_db, secret) -- mirrors reg_client
    in conftest.py."""
    from lablink_allocator_service import main
    from lablink_allocator_service.secret_hash import hash_secret

    secret = "real-client-secret"
    fake_db = MagicMock()
    fake_db.get_client_secret_hash.return_value = hash_secret(secret)
    monkeypatch.setattr(main, "database", fake_db, raising=False)
    return app.test_client(), fake_db, secret


def test_valid_secret_for_that_prefix_is_authorized(tunnel_auth_client):
    client, fake_db, secret = tunnel_auth_client
    prefix = "tun-vm-1-" + "a" * 16
    fake_db.get_tunnel_path_prefix.return_value = ("vm-1", prefix)
    r = client.get(
        "/internal/tunnel_auth",
        headers={"X-Tunnel-Prefix": prefix, "X-Tunnel-Auth": f"Bearer {secret}"},
    )
    assert r.status_code == 200
    # Pin WHICH identity was resolved and whose hash was checked. Without
    # these, a mock that ignores its arguments hides every extraction and
    # identity-confusion bug -- including the one that made this endpoint 401
    # every real attach.
    fake_db.get_tunnel_path_prefix.assert_called_once_with(prefix)
    fake_db.get_client_secret_hash.assert_called_once_with("vm-1")


def test_wrong_secret_is_rejected(tunnel_auth_client):
    client, fake_db, _ = tunnel_auth_client
    prefix = "tun-vm-1-" + "a" * 16
    fake_db.get_tunnel_path_prefix.return_value = ("vm-1", prefix)
    r = client.get(
        "/internal/tunnel_auth",
        headers={"X-Tunnel-Prefix": prefix, "X-Tunnel-Auth": "Bearer nope"},
    )
    assert r.status_code == 401


def test_unknown_prefix_is_rejected(tunnel_auth_client):
    client, fake_db, secret = tunnel_auth_client
    fake_db.get_tunnel_path_prefix.return_value = None
    r = client.get(
        "/internal/tunnel_auth",
        headers={"X-Tunnel-Prefix": "tun-not-a-client", "X-Tunnel-Auth": f"Bearer {secret}"},
    )
    assert r.status_code == 401


def test_client_row_without_a_secret_hash_is_rejected(tunnel_auth_client):
    client, fake_db, secret = tunnel_auth_client
    prefix = "tun-vm-1-" + "a" * 16
    fake_db.get_tunnel_path_prefix.return_value = ("vm-1", prefix)
    fake_db.get_client_secret_hash.return_value = None
    r = client.get(
        "/internal/tunnel_auth",
        headers={"X-Tunnel-Prefix": prefix, "X-Tunnel-Auth": f"Bearer {secret}"},
    )
    assert r.status_code == 401


def test_a_bare_token_without_the_bearer_scheme_is_rejected(tunnel_auth_client):
    """House idiom across this codebase is startswith("Bearer ") then reject;
    accepting a scheme-less token would diverge from every other endpoint."""
    client, fake_db, secret = tunnel_auth_client
    prefix = "tun-vm-1-" + "a" * 16
    fake_db.get_tunnel_path_prefix.return_value = ("vm-1", prefix)
    r = client.get(
        "/internal/tunnel_auth",
        headers={"X-Tunnel-Prefix": prefix, "X-Tunnel-Auth": secret},
    )
    assert r.status_code == 401


def test_missing_header_is_rejected(tunnel_auth_client):
    client, *_ = tunnel_auth_client
    r = client.get("/internal/tunnel_auth", headers={"X-Tunnel-Prefix": "tun-x"})
    assert r.status_code == 401
