"""Tests for the admin VNC peek/connect/release routes."""
from unittest.mock import MagicMock

from lablink_allocator_service.signed_cookie import verify


def _cookie_value(resp) -> str:
    set_cookie = resp.headers["Set-Cookie"]
    return set_cookie.split("lablink_session=")[1].split(";")[0]


def test_peek_requires_auth(client):
    resp = client.get("/admin/instances/host1/peek")
    assert resp.status_code == 401


def test_peek_redirects_to_desktop_with_view_only_cookie(
    client, admin_headers, monkeypatch
):
    fake_db = MagicMock()
    fake_db.get_session_for_peek.return_value = {"sessionid": "sid-123"}
    fake_conn = MagicMock()
    fake_db._pool.getconn.return_value = fake_conn
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=True
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.get_or_create_cookie_secret",
        lambda conn: "test-secret",
    )

    resp = client.get(
        "/admin/instances/host1/peek", headers=admin_headers, follow_redirects=False
    )

    assert resp.status_code == 303
    assert resp.headers["Location"].endswith("/desktop")
    fake_db.get_session_for_peek.assert_called_once_with("host1")

    payload = verify(_cookie_value(resp), secret="test-secret")
    assert payload == "sid-123:view_only"


def test_peek_errors_when_no_active_session(client, admin_headers, monkeypatch):
    fake_db = MagicMock()
    fake_db.get_session_for_peek.return_value = None
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=True
    )

    resp = client.get(
        "/admin/instances/host1/peek", headers=admin_headers, follow_redirects=False
    )

    assert resp.status_code == 302
    assert "vnc_error=peek_unavailable" in resp.headers["Location"]


def test_connect_requires_auth(client):
    resp = client.post("/admin/instances/host1/connect")
    assert resp.status_code == 401


def test_connect_success_redirects_with_admin_session_cookie(
    client, admin_headers, monkeypatch
):
    fake_db = MagicMock()
    fake_db.admin_reserve_vm.return_value = True
    fake_conn = MagicMock()
    fake_db._pool.getconn.return_value = fake_conn
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=True
    )
    monkeypatch.setattr(
        "lablink_allocator_service.providers.connectivity.allocator_proxied."
        "prepare_browser_session",
        lambda **kw: None,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.get_or_create_cookie_secret",
        lambda conn: "test-secret",
    )

    resp = client.post(
        "/admin/instances/host1/connect",
        headers=admin_headers,
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["Location"].endswith("/desktop")
    fake_db.admin_reserve_vm.assert_called_once_with("host1")

    payload = verify(_cookie_value(resp), secret="test-secret")
    session_id, _, suffix = payload.partition(":")
    assert suffix == "admin_session"


def test_connect_raced_when_reserve_fails(client, admin_headers, monkeypatch):
    fake_db = MagicMock()
    fake_db.admin_reserve_vm.return_value = False
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=True
    )

    resp = client.post(
        "/admin/instances/host1/connect",
        headers=admin_headers,
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert "vnc_error=connect_raced" in resp.headers["Location"]


def test_connect_rotation_failure_marks_unhealthy_and_releases(
    client, admin_headers, monkeypatch
):
    from lablink_allocator_service.client_session import RotationFailed

    fake_db = MagicMock()
    fake_db.admin_reserve_vm.return_value = True
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=True
    )

    def _raise(**kw):
        raise RotationFailed("agent unreachable")

    monkeypatch.setattr(
        "lablink_allocator_service.providers.connectivity.allocator_proxied."
        "prepare_browser_session",
        _raise,
    )

    resp = client.post(
        "/admin/instances/host1/connect",
        headers=admin_headers,
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert "vnc_error=rotation_failed" in resp.headers["Location"]
    fake_db.update_health.assert_called_once_with(
        hostname="host1", healthy="Unhealthy"
    )
    fake_db.release_seat.assert_called_once_with(hostname="host1")


def test_release_requires_auth(client):
    resp = client.post("/admin/instances/host1/release")
    assert resp.status_code == 401


def test_release_clears_seat_and_redirects(client, admin_headers, monkeypatch):
    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=True
    )

    resp = client.post(
        "/admin/instances/host1/release",
        headers=admin_headers,
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/admin/instances")
    fake_db.release_seat.assert_called_once_with(hostname="host1")
