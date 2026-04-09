"""Tests for the /api/health endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock


class TestHealthEndpoint:
    def test_healthy_when_all_services_ready(self, client, monkeypatch):
        """Returns 200 with status=healthy when all services are initialized."""
        import lablink_allocator_service.main as main_mod

        monkeypatch.setattr(main_mod, "database", MagicMock())
        monkeypatch.setattr(main_mod, "scheduler_service", MagicMock())
        monkeypatch.setattr(main_mod, "reboot_service", MagicMock())

        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "healthy"
        assert data["checks"]["database"] == "ok"
        assert data["checks"]["scheduler"] == "ok"
        assert data["checks"]["reboot_service"] == "ok"

    def test_starting_when_database_not_ready(self, client, monkeypatch):
        """Returns 503 when database is not yet initialized."""
        import lablink_allocator_service.main as main_mod

        monkeypatch.setattr(main_mod, "database", None)
        monkeypatch.setattr(main_mod, "scheduler_service", MagicMock())
        monkeypatch.setattr(main_mod, "reboot_service", MagicMock())

        resp = client.get("/api/health")
        assert resp.status_code == 503
        data = resp.get_json()
        assert data["status"] == "starting"
        assert data["checks"]["database"] == "not initialized"

    def test_starting_when_scheduler_not_ready(self, client, monkeypatch):
        """Returns 503 when scheduler is not yet initialized."""
        import lablink_allocator_service.main as main_mod

        monkeypatch.setattr(main_mod, "database", MagicMock())
        monkeypatch.setattr(main_mod, "scheduler_service", None)
        monkeypatch.setattr(main_mod, "reboot_service", MagicMock())

        resp = client.get("/api/health")
        assert resp.status_code == 503
        data = resp.get_json()
        assert data["status"] == "starting"
        assert data["checks"]["scheduler"] == "not initialized"

    def test_starting_when_reboot_service_not_ready(self, client, monkeypatch):
        """Returns 503 when reboot service is not yet initialized."""
        import lablink_allocator_service.main as main_mod

        monkeypatch.setattr(main_mod, "database", MagicMock())
        monkeypatch.setattr(main_mod, "scheduler_service", MagicMock())
        monkeypatch.setattr(main_mod, "reboot_service", None)

        resp = client.get("/api/health")
        assert resp.status_code == 503
        data = resp.get_json()
        assert data["status"] == "starting"
        assert data["checks"]["reboot_service"] == "not initialized"

    def test_health_no_auth_required(self, client):
        """Health endpoint should not require authentication."""
        resp = client.get("/api/health")
        assert resp.status_code != 401
