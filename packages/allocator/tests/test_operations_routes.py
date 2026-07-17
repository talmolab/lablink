"""Tests for the GET /api/operations read endpoints."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def fake_operations_db(app, monkeypatch):
    """Wire main.operations_db to a fresh mock for each test."""
    from lablink_allocator_service import main

    fake_db = MagicMock()
    monkeypatch.setattr(main, "operations_db", fake_db, raising=False)
    return fake_db


def test_list_operations_returns_recent_operations(
    fake_operations_db, client, admin_headers,
):
    fake_operations_db.list_operations.return_value = [
        {"id": 2, "op_type": "destroy", "status": "succeeded"},
        {"id": 1, "op_type": "apply", "status": "succeeded"},
    ]

    resp = client.get("/api/operations", headers=admin_headers)

    assert resp.status_code == 200
    body = resp.get_json()
    assert [o["id"] for o in body] == [2, 1]
    fake_operations_db.list_operations.assert_called_once_with(limit=50)


def test_list_operations_requires_auth(fake_operations_db, client):
    resp = client.get("/api/operations")
    assert resp.status_code == 401


def test_list_operations_in_progress_returns_current_job(
    fake_operations_db, client, admin_headers,
):
    fake_operations_db.get_in_progress_operation.return_value = {
        "id": 5, "op_type": "destroy", "status": "running",
    }

    resp = client.get(
        "/api/operations?status=in_progress", headers=admin_headers
    )

    assert resp.status_code == 200
    assert resp.get_json()["id"] == 5
    fake_operations_db.get_in_progress_operation.assert_called_once()


def test_list_operations_in_progress_returns_null_when_idle(
    fake_operations_db, client, admin_headers,
):
    fake_operations_db.get_in_progress_operation.return_value = None

    resp = client.get(
        "/api/operations?status=in_progress", headers=admin_headers
    )

    assert resp.status_code == 200
    assert resp.get_json() is None


def test_get_operation_returns_the_operation(
    fake_operations_db, client, admin_headers,
):
    fake_operations_db.get_operation.return_value = {
        "id": 7, "op_type": "apply", "status": "succeeded", "output": "ok",
    }

    resp = client.get("/api/operations/7", headers=admin_headers)

    assert resp.status_code == 200
    assert resp.get_json()["id"] == 7
    fake_operations_db.get_operation.assert_called_once_with(7)


def test_get_operation_404_when_missing(
    fake_operations_db, client, admin_headers,
):
    fake_operations_db.get_operation.return_value = None

    resp = client.get("/api/operations/999", headers=admin_headers)

    assert resp.status_code == 404


def test_get_operation_requires_auth(fake_operations_db, client):
    resp = client.get("/api/operations/7")
    assert resp.status_code == 401
