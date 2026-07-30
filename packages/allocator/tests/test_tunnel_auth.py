"""Tests for GET/POST /internal/tunnel_auth -- the nginx auth_request gate
for the reverse-tunnel WebSocket attach point.

Security model under test: the URL path prefix identifies which client is
attaching; the bearer token authenticates it. Both must agree -- a client
must not be able to attach under another client's prefix even holding a
valid secret of its own. Missing header, unknown prefix, or mismatched
secret must all fail closed (401) before any per-client state is touched.
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
    prefix = "vm-1-" + "a" * 16
    fake_db.get_tunnel_path_prefix.return_value = ("vm-1", prefix)
    r = client.get(
        "/internal/tunnel_auth",
        headers={"X-Original-URI": f"/tunnel/{prefix}", "X-Tunnel-Auth": f"Bearer {secret}"},
    )
    assert r.status_code == 200


def test_wrong_secret_is_rejected(tunnel_auth_client):
    client, fake_db, _ = tunnel_auth_client
    prefix = "vm-1-" + "a" * 16
    fake_db.get_tunnel_path_prefix.return_value = ("vm-1", prefix)
    r = client.get(
        "/internal/tunnel_auth",
        headers={"X-Original-URI": f"/tunnel/{prefix}", "X-Tunnel-Auth": "Bearer nope"},
    )
    assert r.status_code == 401


def test_unknown_prefix_is_rejected(tunnel_auth_client):
    client, fake_db, secret = tunnel_auth_client
    fake_db.get_tunnel_path_prefix.return_value = None
    r = client.get(
        "/internal/tunnel_auth",
        headers={"X-Original-URI": "/tunnel/not-a-client", "X-Tunnel-Auth": f"Bearer {secret}"},
    )
    assert r.status_code == 401


def test_missing_header_is_rejected(tunnel_auth_client):
    client, *_ = tunnel_auth_client
    r = client.get("/internal/tunnel_auth", headers={"X-Original-URI": "/tunnel/x"})
    assert r.status_code == 401


def test_mismatched_prefix_and_secret_is_rejected(tunnel_auth_client):
    """A client holding a *valid* secret of its own must not be able to
    attach under a different client's prefix. get_tunnel_path_prefix maps
    the requested prefix to "other-vm", whose stored hash is for a
    different secret -- so verify_secret_cached must fail even though the
    token presented is a real, well-formed secret (just not that client's)."""
    from lablink_allocator_service.secret_hash import hash_secret

    client, fake_db, secret = tunnel_auth_client
    other_prefix = "other-vm-" + "b" * 16
    fake_db.get_tunnel_path_prefix.return_value = ("other-vm", other_prefix)
    fake_db.get_client_secret_hash.side_effect = lambda client_id: (
        hash_secret("other-vms-own-secret")
        if client_id == "other-vm"
        else hash_secret(secret)
    )
    r = client.get(
        "/internal/tunnel_auth",
        headers={
            "X-Original-URI": f"/tunnel/{other_prefix}",
            "X-Tunnel-Auth": f"Bearer {secret}",
        },
    )
    assert r.status_code == 401
