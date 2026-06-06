"""POST /api/session-metrics/<hostname>."""

import json
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def app(monkeypatch):
    from lablink_allocator_service import main
    from lablink_allocator_service.secret_hash import hash_secret

    fake_db = MagicMock()
    # argon2 hash of "letmein" — matches the verify_secret() the decorator uses.
    fake_db.get_client_secret_hash.return_value = hash_secret("letmein")
    monkeypatch.setattr(main, "database", fake_db, raising=False)
    main.app.config["TESTING"] = True
    yield main.app, fake_db


def _payload():
    return {
        "session_started_at": "2026-06-05T17:00:00+00:00",
        "counters": {
            "sample_count": 100,
            "seconds_in_subject_software": 200,
            "seconds_in_terminal": 50,
            "seconds_in_browser": 25,
            "seconds_in_other": 125,
            "gpu_active_seconds": 80,
            "gpu_util_peak": 95,
            "vram_used_peak_mb": 14000,
            "seconds_to_first_sleap_label": 300,
            "seconds_to_first_sleap_train": None,
            "seconds_to_first_sleap_track": None,
            "max_labeled_frames": 12,
            "training_epochs_completed": 0,
            "training_final_loss": None,
        },
    }


def test_post_session_metrics_writes_and_returns_200(app):
    flask_app, db = app
    client = flask_app.test_client()
    resp = client.post(
        "/api/session-metrics/vm-1",
        data=json.dumps(_payload()),
        content_type="application/json",
        headers={"Authorization": "Bearer letmein"},
    )
    assert resp.status_code == 200
    db.update_session_metrics.assert_called_once()


def test_post_session_metrics_404_when_unknown_host(app):
    flask_app, db = app
    db.update_session_metrics.side_effect = LookupError("not found")
    client = flask_app.test_client()
    resp = client.post(
        "/api/session-metrics/vm-missing",
        data=json.dumps(_payload()),
        content_type="application/json",
        headers={"Authorization": "Bearer letmein"},
    )
    assert resp.status_code == 404


def test_post_session_metrics_409_when_sealed(app):
    flask_app, db = app
    db.update_session_metrics.side_effect = ValueError("sealed")
    client = flask_app.test_client()
    resp = client.post(
        "/api/session-metrics/vm-1",
        data=json.dumps(_payload()),
        content_type="application/json",
        headers={"Authorization": "Bearer letmein"},
    )
    assert resp.status_code == 409


def test_post_session_metrics_401_without_secret(app):
    flask_app, _ = app
    client = flask_app.test_client()
    resp = client.post(
        "/api/session-metrics/vm-1",
        data=json.dumps(_payload()),
        content_type="application/json",
    )
    assert resp.status_code == 401
