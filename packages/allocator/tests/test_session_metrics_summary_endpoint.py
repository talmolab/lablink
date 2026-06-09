"""GET /api/session-metrics/summary — JSON cohort summary endpoint."""

from unittest.mock import MagicMock

import pytest


_FIXTURE_SUMMARY = {
    "total_vms": 3,
    "funnel": {"started": 3, "labeled": 3, "trained": 2, "tracked": 1},
    "pct_reached_training": 66.7,
    "median_seconds_in_subject_software": 3200,
    "median_seconds_to_first_train": 900,
    "median_labeled_frames": 320,
    "median_epochs_completed": 20,
}


@pytest.fixture
def app_with_metrics(monkeypatch, app):
    from lablink_allocator_service import main

    fake_db = MagicMock()
    fake_db.get_session_metrics_summary.return_value = _FIXTURE_SUMMARY
    monkeypatch.setattr(main, "database", fake_db, raising=False)
    main.cfg.monitoring.enabled = True
    return main.app, fake_db


def test_returns_summary_when_enabled(app_with_metrics, client, admin_headers):
    resp = client.get("/api/session-metrics/summary", headers=admin_headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:500]
    body = resp.get_json()
    assert body["enabled"] is True
    assert body["summary"] == _FIXTURE_SUMMARY
    # conftest's omega_config sets machine.software = "sleap" and
    # monitoring.subject_window_patterns = [], so the label falls back
    # to machine.software.
    assert body["subject_software_label"] == "sleap"


def test_returns_disabled_when_monitoring_off(
    monkeypatch, app_with_metrics, client, admin_headers
):
    from lablink_allocator_service import main

    monkeypatch.setattr(main.cfg.monitoring, "enabled", False)
    resp = client.get("/api/session-metrics/summary", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body == {
        "enabled": False,
        "subject_software_label": "sleap",
        "summary": None,
    }


def test_subject_label_prefers_explicit_pattern(
    monkeypatch, app_with_metrics, client, admin_headers
):
    from lablink_allocator_service import main

    monkeypatch.setattr(
        main.cfg.monitoring, "subject_window_patterns", ["custom_app"]
    )
    resp = client.get("/api/session-metrics/summary", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()["subject_software_label"] == "custom_app"


def test_subject_label_falls_back_to_subject_when_no_software(
    monkeypatch, app_with_metrics, client, admin_headers
):
    from lablink_allocator_service import main

    monkeypatch.setattr(main.cfg.monitoring, "subject_window_patterns", [])
    monkeypatch.setattr(main.cfg.machine, "software", "")
    resp = client.get("/api/session-metrics/summary", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.get_json()["subject_software_label"] == "subject"


def test_requires_auth(app_with_metrics, client):
    app_flask, _ = app_with_metrics
    resp = client.get("/api/session-metrics/summary")
    assert resp.status_code == 401


def test_admin_html_and_json_summary_are_identical(
    app_with_metrics, client, admin_headers
):
    """Locks /admin/session-metrics and /api/session-metrics/summary to one source."""
    from lablink_allocator_service import main

    captured: dict = {}
    original = main.render_template

    def _capturing_render(template, **context):
        captured["context"] = context
        return original(template, **context)

    main.render_template = _capturing_render
    try:
        admin_resp = client.get("/admin/session-metrics", headers=admin_headers)
    finally:
        main.render_template = original

    assert admin_resp.status_code == 200
    api_resp = client.get(
        "/api/session-metrics/summary", headers=admin_headers
    )
    assert api_resp.status_code == 200

    api_body = api_resp.get_json()
    assert captured["context"]["summary"] == api_body["summary"]
    assert (
        captured["context"]["subject_software_label"]
        == api_body["subject_software_label"]
    )
    assert captured["context"]["monitoring_enabled"] == api_body["enabled"]


def test_zero_rows_returns_zeroed_summary(
    monkeypatch, app_with_metrics, client, admin_headers
):
    from lablink_allocator_service import main

    main.database.get_session_metrics_summary.return_value = {
        "total_vms": 0,
        "funnel": {"started": 0, "labeled": 0, "trained": 0, "tracked": 0},
        "pct_reached_training": 0.0,
        "median_seconds_in_subject_software": None,
        "median_seconds_to_first_train": None,
        "median_labeled_frames": None,
        "median_epochs_completed": None,
    }
    resp = client.get("/api/session-metrics/summary", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["enabled"] is True
    assert body["summary"]["total_vms"] == 0
    assert body["summary"]["median_seconds_in_subject_software"] is None
