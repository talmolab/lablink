"""Tests for the client agent's /api/session/start endpoint."""

from datetime import datetime
from unittest.mock import patch

import pytest

from lablink_client_service.agent.api import create_app


@pytest.fixture(autouse=True)
def anchor_path(tmp_path, monkeypatch):
    """Redirect the session-anchor file into tmp_path so the agent never
    writes to /tmp during tests; yield the path so tests can read it back."""
    path = tmp_path / "session-anchor"
    monkeypatch.setenv("LABLINK_SESSION_ANCHOR_PATH", str(path))
    return path


@pytest.fixture
def client(monkeypatch):
    """Flask test client with AGENT_TOKEN set and password rotation
    patched out so tests don't shell out to `kasmvncpasswd`."""
    monkeypatch.setenv("AGENT_TOKEN", "test-token-123")
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


def test_agent_validates_agent_token(monkeypatch):
    """AGENT_TOKEN accepted, wrong token rejected."""
    monkeypatch.setenv("AGENT_TOKEN", "good-agent")
    from lablink_client_service.agent.api import create_app
    app = create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with patch("lablink_client_service.agent.api.rotate_kasmvnc_password"):
        ok = c.post("/api/session/start", json={"password": "p"},
                    headers={"Authorization": "Bearer good-agent"})
        bad = c.post("/api/session/start", json={"password": "p"},
                     headers={"Authorization": "Bearer wrong"})
    assert ok.status_code == 200
    assert bad.status_code == 401


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


def test_session_start_returns_500_when_agent_token_unset(monkeypatch):
    """Misconfigured server (no AGENT_TOKEN env) returns 500 rather than
    silently accepting empty-Bearer rotations — failing closed."""
    monkeypatch.delenv("AGENT_TOKEN", raising=False)
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


def test_session_start_writes_anchor_on_success(client, authed_headers, anchor_path):
    """Happy path also writes the session anchor file so the monitoring
    agent can reset its session_started_at clock."""
    assert not anchor_path.exists()
    with patch("lablink_client_service.agent.api.rotate_kasmvnc_password"):
        resp = client.post(
            "/api/session/start",
            json={"password": "x"},
            headers=authed_headers,
        )
    assert resp.status_code == 200
    assert anchor_path.exists()
    # ISO-8601 UTC timestamp parses round-trip and has timezone info.
    parsed = datetime.fromisoformat(anchor_path.read_text())
    assert parsed.tzinfo is not None


def test_session_start_no_anchor_on_auth_failure(client, anchor_path):
    """401 paths must not write the anchor — only a real assignment
    should reset the user-session clock."""
    with patch("lablink_client_service.agent.api.rotate_kasmvnc_password"):
        resp = client.post("/api/session/start", json={"password": "x"})
    assert resp.status_code == 401
    assert not anchor_path.exists()


def test_session_start_no_anchor_on_rotation_failure(
    client, authed_headers, anchor_path
):
    """If rotation fails we return 500 — anchor must not be written, so
    the monitoring clock keeps its previous value (no false reset)."""
    with patch(
        "lablink_client_service.agent.api.rotate_kasmvnc_password",
        side_effect=RuntimeError("kasmvncpasswd died"),
    ):
        resp = client.post(
            "/api/session/start",
            json={"password": "x"},
            headers=authed_headers,
        )
    assert resp.status_code == 500
    assert not anchor_path.exists()


def test_session_start_succeeds_even_if_anchor_write_fails(
    client, authed_headers, monkeypatch
):
    """Anchor-write failure must not break seat assignment — log and move
    on. The seat is usable; only metric alignment degrades."""
    monkeypatch.setenv("LABLINK_SESSION_ANCHOR_PATH", "/nonexistent-dir/anchor")
    with patch("lablink_client_service.agent.api.rotate_kasmvnc_password"):
        resp = client.post(
            "/api/session/start",
            json={"password": "x"},
            headers=authed_headers,
        )
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
