"""Tests for the client agent's /api/session/start endpoint."""

from unittest.mock import patch

import pytest

from lablink_client_service.agent.api import create_app


@pytest.fixture
def client(monkeypatch):
    """Flask test client with API_TOKEN set and password rotation
    patched out so tests don't shell out to `kasmvncpasswd`."""
    monkeypatch.setenv("API_TOKEN", "test-token-123")
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture
def authed_headers():
    return {"Authorization": "Bearer test-token-123"}


def test_healthz_no_auth(client):
    """/healthz must be unauthenticated for ALB / docker healthchecks."""
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.data == b"ok"


def test_session_start_rotates_password_on_valid_request(client, authed_headers):
    """Happy path: valid token + password rotates and returns 200."""
    with patch(
        "lablink_client_service.agent.api.rotate_kasmvnc_password"
    ) as rotate:
        resp = client.post(
            "/api/session/start",
            json={"password": "hunter22"},
            headers=authed_headers,
        )
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    rotate.assert_called_once_with(password="hunter22")


def test_session_start_rejects_missing_auth_header(client):
    """No Authorization header → 401, no rotation attempted."""
    with patch(
        "lablink_client_service.agent.api.rotate_kasmvnc_password"
    ) as rotate:
        resp = client.post(
            "/api/session/start", json={"password": "x"}
        )
    assert resp.status_code == 401
    rotate.assert_not_called()


def test_session_start_rejects_wrong_token(client):
    """Bearer token mismatch → 401."""
    with patch(
        "lablink_client_service.agent.api.rotate_kasmvnc_password"
    ) as rotate:
        resp = client.post(
            "/api/session/start",
            json={"password": "x"},
            headers={"Authorization": "Bearer wrong-token"},
        )
    assert resp.status_code == 401
    rotate.assert_not_called()


def test_session_start_rejects_non_bearer_scheme(client):
    """Authorization without 'Bearer ' prefix → 401."""
    with patch(
        "lablink_client_service.agent.api.rotate_kasmvnc_password"
    ) as rotate:
        resp = client.post(
            "/api/session/start",
            json={"password": "x"},
            headers={"Authorization": "Basic test-token-123"},
        )
    assert resp.status_code == 401
    rotate.assert_not_called()


def test_session_start_returns_500_when_api_token_unset(monkeypatch):
    """Misconfigured server (no API_TOKEN env) returns 500 rather than
    silently accepting empty-Bearer rotations — failing closed."""
    monkeypatch.delenv("API_TOKEN", raising=False)
    app = create_app()
    app.config["TESTING"] = True
    test_client = app.test_client()

    with patch(
        "lablink_client_service.agent.api.rotate_kasmvnc_password"
    ) as rotate:
        resp = test_client.post(
            "/api/session/start",
            json={"password": "x"},
            headers={"Authorization": "Bearer "},
        )
    assert resp.status_code == 500
    rotate.assert_not_called()


def test_session_start_rejects_missing_password(client, authed_headers):
    """Authenticated request without password in body → 400."""
    with patch(
        "lablink_client_service.agent.api.rotate_kasmvnc_password"
    ) as rotate:
        resp = client.post(
            "/api/session/start", json={}, headers=authed_headers
        )
    assert resp.status_code == 400
    rotate.assert_not_called()


def test_session_start_rejects_non_json_body(client, authed_headers):
    """Non-JSON body is treated as empty body → 400 missing password."""
    with patch(
        "lablink_client_service.agent.api.rotate_kasmvnc_password"
    ) as rotate:
        resp = client.post(
            "/api/session/start", data="not json", headers=authed_headers
        )
    assert resp.status_code == 400
    rotate.assert_not_called()


def test_session_start_returns_500_when_rotation_raises(client, authed_headers):
    """Rotation failure surfaces as 500 so the allocator can
    release_seat instead of redirecting the student to a broken VM."""
    with patch(
        "lablink_client_service.agent.api.rotate_kasmvnc_password",
        side_effect=RuntimeError("kasmvncpasswd died"),
    ) as rotate:
        resp = client.post(
            "/api/session/start",
            json={"password": "x"},
            headers=authed_headers,
        )
    assert resp.status_code == 500
    rotate.assert_called_once()
