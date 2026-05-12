from unittest.mock import patch

import pytest


@pytest.fixture
def client_app(monkeypatch):
    monkeypatch.setenv("REGISTER_TOKEN", "test-register-token")
    from lablink_client_service.agent.api import create_app
    return create_app().test_client()


def test_session_start_requires_bearer(client_app):
    resp = client_app.post("/api/session/start", json={
        "vnc_password": "p", "browser_token": "t",
        "expires_in_seconds": 60})
    assert resp.status_code == 401


def test_session_start_rejects_wrong_bearer(client_app):
    resp = client_app.post(
        "/api/session/start",
        headers={"Authorization": "Bearer wrong"},
        json={"vnc_password": "p", "browser_token": "t",
              "expires_in_seconds": 60},
    )
    assert resp.status_code == 401


def test_session_start_happy_path(client_app):
    with patch("lablink_client_service.agent.api.rotate_kasmvnc_password") \
            as mock_rotate:
        resp = client_app.post(
            "/api/session/start",
            headers={"Authorization": "Bearer test-register-token"},
            json={"vnc_password": "abc", "browser_token": "tok",
                  "expires_in_seconds": 60},
        )
    assert resp.status_code == 200
    mock_rotate.assert_called_once_with(password="abc")


def test_session_start_missing_fields(client_app):
    resp = client_app.post(
        "/api/session/start",
        headers={"Authorization": "Bearer test-register-token"},
        json={"vnc_password": "abc"},
    )
    assert resp.status_code == 400
