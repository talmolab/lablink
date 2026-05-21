"""Tests for the registration API + register-token at-rest hashing."""
import pytest
from unittest.mock import MagicMock


def test_register_token_global_exists():
    from lablink_allocator_service import main
    assert isinstance(main.REGISTER_TOKEN, str)
    assert len(main.REGISTER_TOKEN) >= 32


def test_init_database_upserts_register_token_hash(monkeypatch, omega_config):
    monkeypatch.setattr(
        "lablink_allocator_service.get_config.get_config",
        lambda: omega_config, raising=True,
    )
    from lablink_allocator_service import main
    monkeypatch.setattr(main, "cfg", omega_config, raising=False)

    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.PostgresqlDatabase",
        lambda **kw: fake_db, raising=True,
    )
    main.init_database()

    fake_db.set_setting.assert_called_once()
    args = fake_db.set_setting.call_args[0]
    assert args[0] == "register_token_hash"
    assert args[1].startswith("$argon2")
    assert args[1] != main.REGISTER_TOKEN


def _decorated(monkeypatch, secret_hash_value, header):
    from lablink_allocator_service import main
    from flask import jsonify

    fake_db = MagicMock()
    fake_db.get_client_secret_hash.return_value = secret_hash_value
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    @main.require_client_secret
    def view():
        return jsonify(ok=True), 200

    with main.app.test_request_context(
        "/api/heartbeat", method="POST",
        json={"vm_id": "vm-1"},
        headers=({"Authorization": header} if header else {}),
    ):
        return view()


def test_require_client_secret_accepts_valid(monkeypatch):
    from lablink_allocator_service.secret_hash import hash_secret
    h = hash_secret("sek")
    resp = _decorated(monkeypatch, h, "Bearer sek")
    assert resp[1] == 200


def test_require_client_secret_rejects_wrong(monkeypatch):
    from lablink_allocator_service.secret_hash import hash_secret
    h = hash_secret("sek")
    resp = _decorated(monkeypatch, h, "Bearer nope")
    assert resp[1] == 401


def test_require_client_secret_rejects_missing_header(monkeypatch):
    resp = _decorated(monkeypatch, "$argon2id$h", None)
    assert resp[1] == 401


def test_require_client_secret_rejects_null_hash(monkeypatch):
    resp = _decorated(monkeypatch, None, "Bearer sek")
    assert resp[1] == 401


@pytest.fixture
def reg_client(app, monkeypatch):
    from lablink_allocator_service import main
    from lablink_allocator_service.secret_hash import hash_secret
    from lablink_allocator_service.providers.connectivity.allocator_proxied import (
        AllocatorProxiedClientConnectivity,
    )

    class _StubProvider:
        client_connectivity = AllocatorProxiedClientConnectivity()

    app.config["LABLINK_PROVIDER"] = _StubProvider()

    fake_db = MagicMock()
    fake_db.register_client.return_value = "vm-1"
    monkeypatch.setattr(main, "database", fake_db, raising=False)
    monkeypatch.setattr(main, "REGISTER_TOKEN", "tk_test_register", raising=False)
    fake_db.get_setting.return_value = hash_secret("tk_test_register")
    return app.test_client(), fake_db


def test_register_rejects_bad_token(reg_client):
    client, _ = reg_client
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": "vm-1", "machine_identity": "i-1"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401


def test_register_requires_hostname_and_identity(reg_client):
    client, _ = reg_client
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": "vm-1"},
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 400


def test_register_success_mints_secret(reg_client):
    client, fake_db = reg_client
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": "vm-1", "machine_identity": "i-1",
              "provider": "aws", "endpoint_url": "ws://x:6080",
              "provider_metadata": {"az": "a"}},
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["client_id"] == "vm-1"
    assert isinstance(body["client_secret"], str) and len(body["client_secret"]) >= 32
    assert body["connectivity"] == "allocator_proxied"
    assert body["register_token"] == "tk_test_register"
    assert "allocator_url" in body and "client_image" in body
    kw = fake_db.register_client.call_args.kwargs
    assert kw["client_secret_hash"].startswith("$argon2")
    assert kw["client_secret_hash"] != body["client_secret"]
    assert kw["machine_identity"] == "i-1"


def test_status_requires_client_secret(reg_client):
    client, fake_db = reg_client
    fake_db.get_client_secret_hash.return_value = None
    r = client.get("/api/v1/clients/vm-1/status",
                    headers={"Authorization": "Bearer x"})
    assert r.status_code == 401


def test_status_returns_status(reg_client, monkeypatch):
    from lablink_allocator_service.secret_hash import hash_secret
    client, fake_db = reg_client
    fake_db.get_client_secret_hash.return_value = hash_secret("sek")
    fake_db.get_status_by_hostname.return_value = "running"
    r = client.get("/api/v1/clients/vm-1/status",
                    headers={"Authorization": "Bearer sek"})
    assert r.status_code == 200
    assert r.get_json() == {"client_id": "vm-1", "status": "running"}


def test_register_returns_409_on_none(reg_client):
    client, fake_db = reg_client
    fake_db.register_client.return_value = None
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": "vm-1", "machine_identity": "i-1"},
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 409


def test_register_returns_409_on_integrity_error(reg_client):
    import psycopg2
    client, fake_db = reg_client
    fake_db.register_client.side_effect = psycopg2.IntegrityError("dup")
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": "vm-1", "machine_identity": "i-1"},
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 409


def test_agent_token_global_exists():
    from lablink_allocator_service import main
    assert isinstance(main.AGENT_TOKEN, str) and len(main.AGENT_TOKEN) >= 32
    assert main.AGENT_TOKEN != main.API_TOKEN
    assert main.AGENT_TOKEN != main.REGISTER_TOKEN


def test_register_response_includes_agent_token(reg_client):
    client, fake_db = reg_client
    r = client.post("/api/v1/clients/register",
                     json={"hostname": "vm-1", "machine_identity": "i-1"},
                     headers={"Authorization": "Bearer tk_test_register"})
    assert r.status_code == 200
    from lablink_allocator_service import main
    assert r.get_json()["agent_token"] == main.AGENT_TOKEN


def test_register_response_includes_api_token(reg_client):
    """BYO clients need API_TOKEN so start.sh can POST /api/vm-metrics
    (which is @require_api_token-gated, not per-client). Without this,
    container-startup timing never lands for manual clients."""
    client, fake_db = reg_client
    r = client.post("/api/v1/clients/register",
                     json={"hostname": "vm-1", "machine_identity": "i-1"},
                     headers={"Authorization": "Bearer tk_test_register"})
    assert r.status_code == 200
    from lablink_allocator_service import main
    assert r.get_json()["api_token"] == main.API_TOKEN
