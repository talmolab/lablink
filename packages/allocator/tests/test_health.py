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

    def test_unattached_client_does_not_make_the_allocator_unready(
        self, health_client, monkeypatch
    ):
        """Reported, but not a 503. Observed live 2026-07-31: gating the code
        on client attachment deadlocked client startup -- a registering client
        is unattached by definition until its tunnel is up, its own preflight
        probe waited for a green health check, and that check could not go
        green until the tunnel it was blocking came up. It also failed
        deploy_compose's health poll and made `lablink status` call the
        allocator unhealthy because a *client* was down."""
        from lablink_allocator_service import tunnel_manager

        monkeypatch.setattr(tunnel_manager, "tunnel_status", lambda: "ok")
        monkeypatch.setattr(tunnel_manager, "attached_aliases", lambda: set())
        client, fake_db = health_client
        fake_db.list_tunnel_aliases.return_value = [10]

        resp = client.get("/api/health")
        assert resp.status_code == 200, resp.get_json()
        assert resp.get_json()["status"] == "healthy"
        assert resp.get_json()["checks"]["tunnel"] == "1 client(s) not attached"

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
        resp = client.get("/api/health")
        assert resp.get_json()["checks"]["tunnel"] == "not running"
        # The other side of the line drawn by
        # test_unattached_client_does_not_make_the_allocator_unready: the
        # shared server being down IS the allocator's own dependency failing,
        # so it must still gate readiness.
        assert resp.status_code == 503

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


class _FakeCursor:
    """Stands in for PooledCursor: yields a cursor whose fetchone() returns a
    real tuple. A bare MagicMock is not enough — fetchone() would hand back
    another mock and unpacking it into three names raises."""

    def __init__(self, row=None, error=None):
        self._row = row
        self._error = error

    def __call__(self, _pool):
        return self

    def __enter__(self):
        cursor = MagicMock()
        if self._error is not None:
            cursor.execute.side_effect = self._error
        cursor.fetchone.return_value = self._row
        return cursor

    def __exit__(self, *exc):
        return False


@pytest.fixture
def stats_db(monkeypatch):
    """Patch main.database with a mock exposing .pool, so connection_stats()
    gets past its `is None` guard. Returns the monkeypatch fixture."""
    from lablink_allocator_service import main

    monkeypatch.setattr(main, "database", MagicMock(), raising=False)
    return monkeypatch


class TestConnectionStats:
    """Unit tests for connection_stats(), which reports Postgres connection
    usage for both /api/health/connections and the /admin panel line."""

    def _stats(self, monkeypatch, row=None, error=None):
        import lablink_allocator_service.routes.health as health_mod

        monkeypatch.setattr(
            health_mod, "PooledCursor", _FakeCursor(row=row, error=error)
        )
        return health_mod.connection_stats()

    def test_reports_counts_and_utilization(self, stats_db):
        stats = self._stats(stats_db, row=(61, 0, 300))

        assert stats == {
            "active_connections": 61,
            "idle_in_transaction": 0,
            "max_connections": 300,
            "utilization_percent": 20.3,
            "warning": False,
            "critical": False,
        }

    def test_warning_above_80_percent(self, stats_db):
        stats = self._stats(stats_db, row=(243, 0, 300))

        assert stats["utilization_percent"] == 81.0
        assert stats["warning"] is True
        assert stats["critical"] is False

    def test_critical_above_90_percent(self, stats_db):
        stats = self._stats(stats_db, row=(273, 2, 300))

        assert stats["utilization_percent"] == 91.0
        assert stats["warning"] is True
        assert stats["critical"] is True
        assert stats["idle_in_transaction"] == 2

    def test_max_connections_read_from_postgres_not_hardcoded(self, stats_db):
        """start.sh sets max_connections=300 today and an operator can raise
        it further; the denominator must follow the server, not a literal."""
        stats = self._stats(stats_db, row=(60, 0, 600))

        assert stats["max_connections"] == 600
        assert stats["utilization_percent"] == 10.0

    def test_none_when_database_not_initialized(self, monkeypatch):
        from lablink_allocator_service import main

        monkeypatch.setattr(main, "database", None, raising=False)

        assert self._stats(monkeypatch, row=(61, 0, 300)) is None

    def test_none_on_psycopg2_error(self, stats_db):
        """Covers pool exhaustion too: psycopg2.pool.PoolError subclasses
        psycopg2.Error, so an exhausted pool degrades instead of raising."""
        import psycopg2

        assert self._stats(stats_db, error=psycopg2.Error("nope")) is None

    def test_none_on_unexpected_error(self, stats_db):
        """The catch is deliberately broader than psycopg2.Error. This helper
        is rendered inside /admin, so any exception escaping it 500s the whole
        panel — which is how six existing /admin tests failed when the catch
        was narrow. Don't narrow it again."""
        assert self._stats(stats_db, error=RuntimeError("unexpected")) is None

    def test_no_zero_division_when_max_connections_is_zero(self, stats_db):
        stats = self._stats(stats_db, row=(0, 0, 0))

        assert stats["utilization_percent"] == 0.0


class TestConnectionHealthEndpoint:
    """GET /api/health/connections."""

    def _patch_stats(self, monkeypatch, value):
        import lablink_allocator_service.routes.health as health_mod

        monkeypatch.setattr(health_mod, "connection_stats", lambda: value)

    def test_requires_admin_auth(self, client):
        """Guards against a future edit quietly dropping the decorator and
        publishing connection counts on a Funnel-exposed host."""
        assert client.get("/api/health/connections").status_code == 401

    def test_returns_stats(self, client, admin_headers, monkeypatch):
        self._patch_stats(
            monkeypatch,
            {
                "active_connections": 61,
                "idle_in_transaction": 0,
                "max_connections": 300,
                "utilization_percent": 20.3,
                "warning": False,
                "critical": False,
            },
        )

        resp = client.get("/api/health/connections", headers=admin_headers)

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["status"] == "ok"
        assert body["active_connections"] == 61
        assert body["max_connections"] == 300

    def test_503_when_unreadable(self, client, admin_headers, monkeypatch):
        self._patch_stats(monkeypatch, None)

        resp = client.get("/api/health/connections", headers=admin_headers)

        assert resp.status_code == 503
        assert resp.get_json()["status"] == "unavailable"

    def test_200_when_saturated(self, client, admin_headers, monkeypatch):
        """Busy is not broken: a saturated pool must not answer non-200, or
        anything treating status codes as liveness will try to restart the
        allocator for being popular."""
        self._patch_stats(
            monkeypatch,
            {
                "active_connections": 295,
                "idle_in_transaction": 0,
                "max_connections": 300,
                "utilization_percent": 98.3,
                "warning": True,
                "critical": True,
            },
        )

        resp = client.get("/api/health/connections", headers=admin_headers)

        assert resp.status_code == 200
        assert resp.get_json()["critical"] is True


class TestAdminPanelConnectionLine:
    """The /admin panel renders the same numbers server-side.

    Patches admin_pages.connection_stats, not health.connection_stats:
    admin_pages binds the name at import time, so patching the definition site
    would not be seen here.
    """

    def _patch_stats(self, monkeypatch, value):
        import lablink_allocator_service.routes.admin_pages as admin_mod

        monkeypatch.setattr(admin_mod, "connection_stats", lambda: value)

    def test_renders_the_line(self, client, admin_headers, monkeypatch):
        self._patch_stats(
            monkeypatch,
            {
                "active_connections": 61,
                "idle_in_transaction": 0,
                "max_connections": 300,
                "utilization_percent": 20.3,
                "warning": False,
                "critical": False,
            },
        )

        html = client.get("/admin", headers=admin_headers).data.decode()

        assert "61 / 300" in html
        assert "20.3%" in html

    def test_critical_renders_an_actionable_banner(
        self, client, admin_headers, monkeypatch
    ):
        """At critical the line escalates to a banner that says what is at
        stake and what to change — a red number alone doesn't tell an operator
        what to do about it."""
        self._patch_stats(
            monkeypatch,
            {
                "active_connections": 295,
                "idle_in_transaction": 0,
                "max_connections": 300,
                "utilization_percent": 98.3,
                "warning": True,
                "critical": True,
            },
        )

        html = client.get("/admin", headers=admin_headers).data.decode()

        assert "connections critical" in html
        assert "Database connections critical" in html
        assert "may be refused" in html
        assert "LABLINK_DB_POOL_MAX_SIZE" in html
        # No leak to report, so no leak sentence.
        assert "idle in transaction" not in html

    def test_critical_points_at_a_leak_when_there_is_one(
        self, client, admin_headers, monkeypatch
    ):
        """Saturation caused by leaked connections has a different fix than
        saturation caused by load, so name it when the count is non-zero."""
        self._patch_stats(
            monkeypatch,
            {
                "active_connections": 295,
                "idle_in_transaction": 7,
                "max_connections": 300,
                "utilization_percent": 98.3,
                "warning": True,
                "critical": True,
            },
        )

        html = client.get("/admin", headers=admin_headers).data.decode()

        assert "7 connection(s) idle in transaction" in html

    def test_warning_stays_a_plain_line(self, client, admin_headers, monkeypatch):
        """80% is worth noticing, not worth a banner. Escalating here would
        train operators to ignore the banner that matters."""
        self._patch_stats(
            monkeypatch,
            {
                "active_connections": 243,
                "idle_in_transaction": 0,
                "max_connections": 300,
                "utilization_percent": 81.0,
                "warning": True,
                "critical": False,
            },
        )

        html = client.get("/admin", headers=admin_headers).data.decode()

        assert "connections warning" in html
        assert "243 / 300" in html
        assert "Database connections critical" not in html
        assert "may be refused" not in html

    def test_degrades_without_breaking_the_panel(
        self, client, admin_headers, monkeypatch
    ):
        """A database problem costs one line, not the whole admin page."""
        self._patch_stats(monkeypatch, None)

        resp = client.get("/admin", headers=admin_headers)
        html = resp.data.decode()

        assert resp.status_code == 200
        assert "DB connections unavailable" in html
        assert "View Current Instances" in html
