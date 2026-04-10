"""Tests for the GET /api/export-metrics endpoint."""

from datetime import datetime
from unittest.mock import MagicMock

EXPORT_METRICS_ENDPOINT = "/api/export-metrics"


def test_export_metrics_success(client, admin_headers, monkeypatch):
    """Test exporting metrics returns correct JSON structure."""
    fake_db = MagicMock()
    fake_db.get_all_vms_for_export.return_value = [
        {
            "hostname": "vm-1",
            "useremail": "user@example.com",
            "inuse": False,
            "healthy": "Healthy",
            "status": "running",
            "terraformapplydurationseconds": 45.0,
            "createdat": "2023-01-01T00:00:00",
        },
        {
            "hostname": "vm-2",
            "useremail": "user2@example.com",
            "inuse": True,
            "healthy": "Healthy",
            "status": "running",
            "terraformapplydurationseconds": 50.0,
            "createdat": "2023-01-01T00:01:00",
        },
    ]
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.get(EXPORT_METRICS_ENDPOINT, headers=admin_headers)

    assert resp.status_code == 200
    assert resp.is_json
    result = resp.get_json()
    assert result["count"] == 2
    assert len(result["vms"]) == 2
    assert result["vms"][0]["hostname"] == "vm-1"
    assert result["vms"][1]["hostname"] == "vm-2"
    fake_db.get_all_vms_for_export.assert_called_once_with(include_logs=False)


def test_export_metrics_include_logs(client, admin_headers, monkeypatch):
    """Test that include_logs=true query param is passed through."""
    fake_db = MagicMock()
    fake_db.get_all_vms_for_export.return_value = [
        {
            "hostname": "vm-1",
            "cloudinitlogs": "some logs",
            "dockerlogs": "docker logs",
        },
    ]
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.get(
        f"{EXPORT_METRICS_ENDPOINT}?include_logs=true",
        headers=admin_headers,
    )

    assert resp.status_code == 200
    result = resp.get_json()
    assert result["vms"][0]["cloudinitlogs"] == "some logs"
    fake_db.get_all_vms_for_export.assert_called_once_with(include_logs=True)


def test_export_metrics_auth_required(client):
    """Test that endpoint requires authentication."""
    resp = client.get(EXPORT_METRICS_ENDPOINT)

    assert resp.status_code == 401


def test_export_metrics_empty(client, admin_headers, monkeypatch):
    """Test exporting when no VMs exist."""
    fake_db = MagicMock()
    fake_db.get_all_vms_for_export.return_value = []
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.get(EXPORT_METRICS_ENDPOINT, headers=admin_headers)

    assert resp.status_code == 200
    result = resp.get_json()
    assert result == {"vms": [], "count": 0}


def test_export_metrics_datetime_serialization(
    client, admin_headers, monkeypatch
):
    """Test that datetime objects are serialized to ISO format strings."""
    fake_db = MagicMock()
    fake_db.get_all_vms_for_export.return_value = [
        {
            "hostname": "vm-1",
            "terraformapplystarttime": datetime(2023, 1, 1, 12, 0, 0),
            "terraformapplyendtime": datetime(2023, 1, 1, 12, 2, 0),
            "createdat": datetime(2023, 1, 1, 10, 0, 0),
        },
    ]
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.get(EXPORT_METRICS_ENDPOINT, headers=admin_headers)

    assert resp.status_code == 200
    result = resp.get_json()
    vm = result["vms"][0]
    assert vm["terraformapplystarttime"] == "2023-01-01T12:00:00"
    assert vm["terraformapplyendtime"] == "2023-01-01T12:02:00"
    assert vm["createdat"] == "2023-01-01T10:00:00"
