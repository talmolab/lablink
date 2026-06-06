"""CSV format on /api/export-metrics."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def app_with_db(monkeypatch, app, admin_headers):
    """Wire a fake DB so /api/export-metrics has deterministic rows.

    Depends on the conftest `app` fixture (Flask test context).
    """
    from lablink_allocator_service import main

    fake_db = MagicMock()
    fake_db.get_all_vms_for_export.return_value = [
        {
            "HostName": "vm-1",
            "UserEmail": "alice@lab.org",
            "SecondsInSubjectSoftware": 4820,
        },
        {
            "HostName": "vm-2",
            "UserEmail": "bob@lab.org",
            "SecondsInSubjectSoftware": 820,
        },
    ]
    monkeypatch.setattr(main, "database", fake_db, raising=False)
    return main.app, admin_headers


def test_format_csv_returns_csv_with_header(app_with_db, client):
    flask_app, admin_headers = app_with_db
    resp = client.get("/api/export-metrics?format=csv", headers=admin_headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert resp.mimetype == "text/csv"
    body = resp.get_data(as_text=True)
    assert "HostName,UserEmail,SecondsInSubjectSoftware" in body
    assert "vm-1,alice@lab.org,4820" in body
    assert "vm-2,bob@lab.org,820" in body


def test_format_csv_sets_content_disposition(app_with_db, client):
    flask_app, admin_headers = app_with_db
    resp = client.get("/api/export-metrics?format=csv", headers=admin_headers)
    cd = resp.headers.get("Content-Disposition", "")
    assert "attachment" in cd
    assert "lablink-session-metrics-" in cd
    assert cd.endswith('.csv"')


def test_default_format_still_json(app_with_db, client):
    flask_app, admin_headers = app_with_db
    resp = client.get("/api/export-metrics", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.is_json
    body = resp.get_json()
    assert "vms" in body
