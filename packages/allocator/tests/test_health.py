"""Tests for the /api/health endpoint."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock


class TestTailscaleStatus:
    """Unit tests for _tailscale_status(), which shells out to `ip` to
    check for an actual Tailscale IPv4 address on tailscale0 rather than
    just the interface's existence — confirmed live against a real
    tailnet that the interface stays up with only a link-local IPv6
    address while the node is logged out, which an existence-only check
    would misreport as "ok"."""

    def test_ok_when_ipv4_address_present(self, monkeypatch):
        import lablink_allocator_service.main as main_mod

        monkeypatch.setattr(
            main_mod.subprocess,
            "run",
            lambda *a, **k: MagicMock(
                returncode=0,
                stdout="17: tailscale0 inet 100.87.100.2/32 scope global tailscale0\n",
            ),
        )

        assert main_mod._tailscale_status() == "ok"

    def test_not_joined_when_only_ipv6_link_local(self, monkeypatch):
        """The false-positive case found live: interface up, no IPv4."""
        import lablink_allocator_service.main as main_mod

        monkeypatch.setattr(
            main_mod.subprocess,
            "run",
            lambda *a, **k: MagicMock(returncode=0, stdout=""),
        )

        assert main_mod._tailscale_status() == "not joined"

    def test_not_joined_when_interface_absent(self, monkeypatch):
        import lablink_allocator_service.main as main_mod

        monkeypatch.setattr(
            main_mod.subprocess,
            "run",
            lambda *a, **k: MagicMock(returncode=1, stdout=""),
        )

        assert main_mod._tailscale_status() == "not joined"

    def test_not_joined_when_ip_binary_missing(self, monkeypatch):
        import lablink_allocator_service.main as main_mod

        def _raise(*a, **k):
            raise OSError("ip: command not found")

        monkeypatch.setattr(main_mod.subprocess, "run", _raise)

        assert main_mod._tailscale_status() == "not joined"

    def test_not_joined_on_timeout(self, monkeypatch):
        import lablink_allocator_service.main as main_mod

        def _raise(*a, **k):
            raise subprocess.TimeoutExpired(cmd="ip", timeout=5)

        monkeypatch.setattr(main_mod.subprocess, "run", _raise)

        assert main_mod._tailscale_status() == "not joined"


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

    def test_tailscale_check_absent_when_not_mesh_overlay(self, client, monkeypatch):
        """A connectivity strategy that doesn't require a tailscale check
        (e.g. lan_direct/allocator_proxied) must not add a tailscale key —
        byte-identical health payload to today for every existing deployment."""
        import lablink_allocator_service.main as main_mod

        monkeypatch.setattr(main_mod, "database", MagicMock())
        monkeypatch.setattr(main_mod, "scheduler_service", MagicMock())
        monkeypatch.setattr(main_mod, "reboot_service", MagicMock())
        monkeypatch.setattr(
            main_mod.app.config["LABLINK_PROVIDER"].client_connectivity,
            "requires_tailscale_check",
            False,
        )

        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert "tailscale" not in resp.get_json()["checks"]

    def test_tailscale_check_ok_when_joined(self, client, monkeypatch):
        import lablink_allocator_service.main as main_mod

        monkeypatch.setattr(main_mod, "database", MagicMock())
        monkeypatch.setattr(main_mod, "scheduler_service", MagicMock())
        monkeypatch.setattr(main_mod, "reboot_service", MagicMock())
        monkeypatch.setattr(
            main_mod.app.config["LABLINK_PROVIDER"].client_connectivity,
            "requires_tailscale_check",
            True,
        )
        monkeypatch.setattr(main_mod, "_tailscale_status", lambda: "ok")

        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.get_json()["checks"]["tailscale"] == "ok"

    def test_tailscale_check_not_joined_marks_unhealthy(self, client, monkeypatch):
        import lablink_allocator_service.main as main_mod

        monkeypatch.setattr(main_mod, "database", MagicMock())
        monkeypatch.setattr(main_mod, "scheduler_service", MagicMock())
        monkeypatch.setattr(main_mod, "reboot_service", MagicMock())
        monkeypatch.setattr(
            main_mod.app.config["LABLINK_PROVIDER"].client_connectivity,
            "requires_tailscale_check",
            True,
        )
        monkeypatch.setattr(main_mod, "_tailscale_status", lambda: "not joined")

        resp = client.get("/api/health")
        assert resp.status_code == 503
        data = resp.get_json()
        assert data["status"] == "starting"
        assert data["checks"]["tailscale"] == "not joined"
