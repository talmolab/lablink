"""Admin /admin/session-metrics rendering and auth."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def app_with_summary(monkeypatch, app):
    from lablink_allocator_service import main

    fake_db = MagicMock()
    fake_db.get_session_metrics_summary.return_value = {
        "total_vms": 3,
        "funnel": {"started": 3, "labeled": 3, "trained": 2, "tracked": 1},
        "pct_reached_training": 66.7,
        "median_seconds_in_subject_software": 3200,
        "median_seconds_to_first_train": 900,
        "median_labeled_frames": 320,
        "median_epochs_completed": 20,
    }
    # Postgres folds unquoted identifiers to lowercase, so the dict that
    # psycopg2 hands back from get_all_vms_for_export() has lowercase keys
    # — mirror that here so the template's vm.hostname / vm.useremail
    # references actually resolve (a CamelCase fixture lets the test pass
    # while the real page renders blank rows).
    fake_db.get_all_vms_for_export.return_value = [
        {
            "hostname": "vm-1",
            "useremail": "alice@lab.org",
            "status": "assigned",
            "sessionmetricsstartedat": "2026-06-05T17:00:00+00:00",
            "sessionmetricssealedat": "2026-06-05T19:14:08+00:00",
            "secondsinsubjectsoftware": 4820,
            "gpuactiveseconds": 1640,
            "secondstofirstsleaplabel": 312,
            "secondstofirstsleaptrain": 1080,
            "secondstofirstsleaptrack": 3120,
            "maxlabeledframes": 480,
            "trainingepochscompleted": 35,
            "trainingfinalloss": 0.0142,
        }
    ]
    monkeypatch.setattr(main, "database", fake_db, raising=False)
    # Make sure monitoring is enabled in the fixture cfg
    main.cfg.monitoring.enabled = True
    return main.app


def test_page_renders_with_summary_and_table(app_with_summary, client, admin_headers):
    resp = client.get("/admin/session-metrics", headers=admin_headers)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:500]
    body = resp.get_data(as_text=True)
    assert "Session metrics" in body
    assert "alice@lab.org" in body
    assert "Download CSV" in body
    assert "Download JSON" in body
    for label in ("Started", "Labeled", "Trained", "Tracked"):
        assert label in body


def test_page_requires_auth(app_with_summary, client):
    resp = client.get("/admin/session-metrics")
    assert resp.status_code == 401


def test_page_renders_empty_state_when_monitoring_disabled(
    monkeypatch, app_with_summary, client, admin_headers
):
    from lablink_allocator_service import main

    monkeypatch.setattr(main.cfg.monitoring, "enabled", False)
    resp = client.get("/admin/session-metrics", headers=admin_headers)
    assert resp.status_code == 200
    assert "monitoring.enabled" in resp.get_data(as_text=True)
