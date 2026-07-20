import uuid
from unittest.mock import patch

from lablink_allocator_service.providers.protocol import (
    ClientConnectivity,
    BrowserSessionTarget,
)


def test_satisfies_protocol_and_name():
    from lablink_allocator_service.providers.connectivity.mesh_overlay import (
        MeshOverlayClientConnectivity,
    )

    conn = MeshOverlayClientConnectivity()
    assert isinstance(conn, ClientConnectivity)
    assert conn.name == "mesh_overlay"


def test_delegates_to_client_session_with_overlay_fallback():
    """prepare_browser_session delegates to client_session.prepare_browser_session
    and injects the overlay-hostname resolver via the fallback_fn kwarg —
    same extension point AllocatorProxiedClientConnectivity uses for its
    EC2 fallback (SR-F1: no AWS/Tailscale-specific imports in client_session)."""
    from lablink_allocator_service.providers.connectivity.mesh_overlay import (
        MeshOverlayClientConnectivity,
        _resolve_overlay_host,
    )

    sentinel = BrowserSessionTarget(ws_url="proxy/tok", browser_credential=None)
    sid = uuid.uuid4()
    with patch(
        "lablink_allocator_service.providers.connectivity.mesh_overlay."
        "prepare_browser_session",
        return_value=sentinel,
    ) as m:
        conn = MeshOverlayClientConnectivity()
        out = conn.prepare_browser_session(
            database="DB",
            hostname="vm-1",
            session_id=sid,
            browser_token="tok",
            agent_token="api",
        )
    assert out is sentinel
    m.assert_called_once_with(
        database="DB",
        hostname="vm-1",
        session_id=sid,
        browser_token="tok",
        agent_token="api",
        fallback_fn=_resolve_overlay_host,
    )


def test_resolve_overlay_host_builds_magicdns_name():
    from lablink_allocator_service.providers.connectivity.mesh_overlay import (
        _resolve_overlay_host,
    )

    mock_db = type("DB", (), {"get_overlay_hostname": staticmethod(
        lambda hostname: "classroom-gpu-3"
    )})()
    mock_cfg = type("Cfg", (), {"manual": type("M", (), {"overlay_tailnet": "example.ts.net"})()})()

    with patch(
        "lablink_allocator_service.providers.connectivity.mesh_overlay._db",
        return_value=mock_db,
    ), patch(
        "lablink_allocator_service.providers.connectivity.mesh_overlay.get_config",
        return_value=mock_cfg,
    ):
        result = _resolve_overlay_host("vm-1")
    assert result == "classroom-gpu-3.example.ts.net"


def test_resolve_overlay_host_raises_when_not_registered():
    from lablink_allocator_service.client_session import RotationFailed
    from lablink_allocator_service.providers.connectivity.mesh_overlay import (
        _resolve_overlay_host,
    )

    mock_db = type("DB", (), {"get_overlay_hostname": staticmethod(lambda hostname: None)})()

    with patch(
        "lablink_allocator_service.providers.connectivity.mesh_overlay._db",
        return_value=mock_db,
    ), patch(
        "lablink_allocator_service.providers.connectivity.mesh_overlay.get_config",
    ):
        try:
            _resolve_overlay_host("vm-1")
            assert False, "expected RotationFailed"
        except RotationFailed as e:
            assert "vm-1" in str(e)


def test_resolve_overlay_host_raises_when_tailnet_not_configured():
    from lablink_allocator_service.client_session import RotationFailed
    from lablink_allocator_service.providers.connectivity.mesh_overlay import (
        _resolve_overlay_host,
    )

    mock_db = type("DB", (), {"get_overlay_hostname": staticmethod(
        lambda hostname: "classroom-gpu-3"
    )})()
    mock_cfg = type("Cfg", (), {"manual": type("M", (), {"overlay_tailnet": ""})()})()

    with patch(
        "lablink_allocator_service.providers.connectivity.mesh_overlay._db",
        return_value=mock_db,
    ), patch(
        "lablink_allocator_service.providers.connectivity.mesh_overlay.get_config",
        return_value=mock_cfg,
    ):
        try:
            _resolve_overlay_host("vm-1")
            assert False, "expected RotationFailed"
        except RotationFailed as e:
            assert "overlay_tailnet" in str(e)


def test_make_join_material_returns_mesh_overlay():
    from lablink_allocator_service.providers.connectivity.mesh_overlay import (
        MeshOverlayClientConnectivity,
    )
    from lablink_allocator_service.providers.protocol import ClientJoinMaterial

    c = MeshOverlayClientConnectivity()
    m = c.make_join_material(
        allocator_url="http://a:5000",
        client_image="img:1",
        register_token="tk_1",
    )
    assert isinstance(m, ClientJoinMaterial)
    assert m.connectivity == "mesh_overlay"
    assert m.allocator_url == "http://a:5000"
    assert m.client_image == "img:1"
    assert m.register_token == "tk_1"
