"""Tests for the /api/health endpoint."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def health_client(app, monkeypatch):
    """HTTP client wired for reverse-tunnel health checks: a stub provider
    whose client_connectivity requires the tunnel check (the real
    ReverseTunnelClientConnectivity, which sets requires_tunnel_check =
    True), and a fake db standing in for main.database.

    Returns (test_client, fake_db).
    """
    from lablink_allocator_service import main
    from lablink_allocator_service.providers.connectivity.reverse_tunnel import (
        ReverseTunnelClientConnectivity,
    )

    class _StubProvider:
        client_connectivity = ReverseTunnelClientConnectivity()

    app.config["LABLINK_PROVIDER"] = _StubProvider()

    fake_db = MagicMock()
    monkeypatch.setattr(main, "database", fake_db, raising=False)
    monkeypatch.setattr(main, "scheduler_service", MagicMock(), raising=False)
    monkeypatch.setattr(main, "reboot_service", MagicMock(), raising=False)

    return app.test_client(), fake_db


class TestTailscaleStatus:
    """Unit tests for _tailscale_status(), which shells out to `ip` to
    check for an actual Tailscale IPv4 address on tailscale0 rather than
    just the interface's existence — confirmed live against a real
    tailnet that the interface stays up with only a link-local IPv6
    address while the node is logged out, which an existence-only check
    would misreport as "ok"."""

    def test_ok_when_ipv4_address_present(self, monkeypatch):
        import lablink_allocator_service.routes.health as health_mod

        monkeypatch.setattr(
            health_mod.subprocess,
            "run",
            lambda *a, **k: MagicMock(
                returncode=0,
                stdout="17: tailscale0 inet 100.87.100.2/32 scope global tailscale0\n",
            ),
        )

        assert health_mod._tailscale_status() == "ok"

    def test_not_joined_when_only_ipv6_link_local(self, monkeypatch):
        """The false-positive case found live: interface up, no IPv4."""
        import lablink_allocator_service.routes.health as health_mod

        monkeypatch.setattr(
            health_mod.subprocess,
            "run",
            lambda *a, **k: MagicMock(returncode=0, stdout=""),
        )

        assert health_mod._tailscale_status() == "not joined"

    def test_not_joined_when_interface_absent(self, monkeypatch):
        import lablink_allocator_service.routes.health as health_mod

        monkeypatch.setattr(
            health_mod.subprocess,
            "run",
            lambda *a, **k: MagicMock(returncode=1, stdout=""),
        )

        assert health_mod._tailscale_status() == "not joined"

    def test_not_joined_when_ip_binary_missing(self, monkeypatch):
        import lablink_allocator_service.routes.health as health_mod

        def _raise(*a, **k):
            raise OSError("ip: command not found")

        monkeypatch.setattr(health_mod.subprocess, "run", _raise)

        assert health_mod._tailscale_status() == "not joined"

    def test_not_joined_on_timeout(self, monkeypatch):
        import lablink_allocator_service.routes.health as health_mod

        def _raise(*a, **k):
            raise subprocess.TimeoutExpired(cmd="ip", timeout=5)

        monkeypatch.setattr(health_mod.subprocess, "run", _raise)

        assert health_mod._tailscale_status() == "not joined"


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
        import lablink_allocator_service.routes.health as health_mod

        monkeypatch.setattr(main_mod, "database", MagicMock())
        monkeypatch.setattr(main_mod, "scheduler_service", MagicMock())
        monkeypatch.setattr(main_mod, "reboot_service", MagicMock())
        monkeypatch.setattr(
            main_mod.app.config["LABLINK_PROVIDER"].client_connectivity,
            "requires_tailscale_check",
            True,
        )
        monkeypatch.setattr(health_mod, "_tailscale_status", lambda: "ok")

        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.get_json()["checks"]["tailscale"] == "ok"

    def test_tailscale_check_not_joined_marks_unhealthy(self, client, monkeypatch):
        import lablink_allocator_service.main as main_mod
        import lablink_allocator_service.routes.health as health_mod

        monkeypatch.setattr(main_mod, "database", MagicMock())
        monkeypatch.setattr(main_mod, "scheduler_service", MagicMock())
        monkeypatch.setattr(main_mod, "reboot_service", MagicMock())
        monkeypatch.setattr(
            main_mod.app.config["LABLINK_PROVIDER"].client_connectivity,
            "requires_tailscale_check",
            True,
        )
        monkeypatch.setattr(health_mod, "_tailscale_status", lambda: "not joined")

        resp = client.get("/api/health")
        assert resp.status_code == 503
        data = resp.get_json()
        assert data["status"] == "starting"
        assert data["checks"]["tailscale"] == "not joined"


class TestTunnelStatus:
    """Health for reverse_tunnel must report *attachment*, not liveness: a
    bound loopback listener survives for the idle timeout after its client
    disconnects, and connections to that orphan hang rather than fail, so
    the shared tunnel server being up says nothing about any one client."""

    def test_health_reports_unattached_clients(self, health_client, monkeypatch):
        """A bound port is not evidence of an attached client: wstunnel keeps
        the listener for its idle timeout after the client leaves, and
        connections to an orphan hang instead of failing."""
        from lablink_allocator_service import tunnel_manager

        monkeypatch.setattr(tunnel_manager, "tunnel_status", lambda: "ok")
        monkeypatch.setattr(tunnel_manager, "attached_aliases", lambda: {10})
        client, fake_db = health_client
        fake_db.list_tunnel_aliases.return_value = [10, 11]

        body = client.get("/api/health").get_json()
        assert body["checks"]["tunnel"] == "1 client(s) not attached"

    def test_health_ok_when_every_client_is_attached(self, health_client, monkeypatch):
        from lablink_allocator_service import tunnel_manager

        monkeypatch.setattr(tunnel_manager, "tunnel_status", lambda: "ok")
        monkeypatch.setattr(tunnel_manager, "attached_aliases", lambda: {10, 11})
        client, fake_db = health_client
        fake_db.list_tunnel_aliases.return_value = [10, 11]

        assert client.get("/api/health").get_json()["checks"]["tunnel"] == "ok"

    def test_health_reports_server_down(self, health_client, monkeypatch):
        from lablink_allocator_service import tunnel_manager

        monkeypatch.setattr(tunnel_manager, "tunnel_status", lambda: "not running")
        client, fake_db = health_client
        fake_db.list_tunnel_aliases.return_value = []
        assert client.get("/api/health").get_json()["checks"]["tunnel"] == "not running"

    def test_health_ok_when_no_clients_registered(self, health_client, monkeypatch):
        """Shared server up, zero registered tunnel clients: the empty
        set has nothing missing from it, so this is the logically safe
        'ok' case, not a degenerate one."""
        from lablink_allocator_service import tunnel_manager

        monkeypatch.setattr(tunnel_manager, "tunnel_status", lambda: "ok")
        monkeypatch.setattr(tunnel_manager, "attached_aliases", lambda: {10})
        client, fake_db = health_client
        fake_db.list_tunnel_aliases.return_value = []

        assert client.get("/api/health").get_json()["checks"]["tunnel"] == "ok"

    def test_health_degrades_when_db_query_fails(self, health_client, monkeypatch):
        """A transient Postgres problem (pool exhaustion, a brief restart)
        while the tunnel server is up must degrade this one check's value,
        not raise out of the route and 500 the whole endpoint -- the same
        contract _tailscale_status keeps for its own external call."""
        import psycopg2

        from lablink_allocator_service import tunnel_manager

        monkeypatch.setattr(tunnel_manager, "tunnel_status", lambda: "ok")
        client, fake_db = health_client
        fake_db.list_tunnel_aliases.side_effect = psycopg2.OperationalError(
            "connection pool exhausted"
        )

        resp = client.get("/api/health")
        assert resp.status_code == 503
        assert resp.get_json()["checks"]["tunnel"] == "client list unavailable"

    def test_health_tunnel_not_initialized_when_db_absent(
        self, health_client, monkeypatch
    ):
        """main.database can in principle be None (mirrors the top-level
        `database` check's own guard); _tunnel_status must report that
        rather than raise AttributeError reaching for list_tunnel_aliases."""
        from lablink_allocator_service import main
        from lablink_allocator_service import tunnel_manager

        monkeypatch.setattr(tunnel_manager, "tunnel_status", lambda: "ok")
        client, _fake_db = health_client
        monkeypatch.setattr(main, "database", None)

        resp = client.get("/api/health")
        assert resp.get_json()["checks"]["tunnel"] == "not initialized"

    def test_tunnel_check_absent_when_not_reverse_tunnel(self, client, monkeypatch):
        """A connectivity strategy that doesn't require a tunnel check
        (e.g. lan_direct/allocator_proxied/mesh_overlay) must not add a
        tunnel key — byte-identical health payload to today for every
        existing deployment."""
        from lablink_allocator_service import main as main_mod

        monkeypatch.setattr(main_mod, "database", MagicMock())
        monkeypatch.setattr(main_mod, "scheduler_service", MagicMock())
        monkeypatch.setattr(main_mod, "reboot_service", MagicMock())

        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert "tunnel" not in resp.get_json()["checks"]
