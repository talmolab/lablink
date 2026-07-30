import uuid
from unittest.mock import patch

import pytest

from lablink_allocator_service.providers.protocol import (
    BrowserSessionTarget,
    ClientConnectivity,
    ClientJoinMaterial,
)


def test_satisfies_protocol_and_flags():
    from lablink_allocator_service.providers.connectivity.reverse_tunnel import (
        ReverseTunnelClientConnectivity,
    )

    c = ReverseTunnelClientConnectivity()
    assert isinstance(c, ClientConnectivity)
    assert c.name == "reverse_tunnel"
    assert c.requires_tailscale_check is False
    assert c.requires_tunnel_check is True


def test_registry_resolves_the_strategy():
    from lablink_allocator_service.providers.registry import get_provider

    prov = get_provider(
        "manual", region=None, terraform_dir=None, connectivity="reverse_tunnel"
    )
    assert prov.client_connectivity.name == "reverse_tunnel"


def test_validator_accepts_the_connectivity_value():
    from lablink_allocator_service.validate_config import VALID_CONNECTIVITY

    assert "reverse_tunnel" in VALID_CONNECTIVITY


def test_delegates_to_client_session_with_tunnel_alias_fallback():
    """prepare_browser_session delegates to client_session.prepare_browser_session
    and injects the tunnel-alias resolver via the fallback_fn kwarg — the same
    extension point MeshOverlayClientConnectivity uses for its overlay-hostname
    fallback."""
    from lablink_allocator_service.providers.connectivity.reverse_tunnel import (
        ReverseTunnelClientConnectivity,
        _resolve_tunnel_alias,
    )

    sentinel = BrowserSessionTarget(ws_url="proxy/tok", browser_credential=None)
    sid = uuid.uuid4()
    with patch(
        "lablink_allocator_service.providers.connectivity.reverse_tunnel."
        "prepare_browser_session",
        return_value=sentinel,
    ) as m:
        conn = ReverseTunnelClientConnectivity()
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
        fallback_fn=_resolve_tunnel_alias,
    )


def test_resolve_tunnel_alias_builds_loopback_address():
    from lablink_allocator_service.providers.connectivity.reverse_tunnel import (
        _resolve_tunnel_alias,
    )

    mock_db = type(
        "DB", (), {"get_tunnel_alias": staticmethod(lambda hostname: 12)}
    )()
    with patch(
        "lablink_allocator_service.providers.connectivity.reverse_tunnel._db",
        return_value=mock_db,
    ):
        result = _resolve_tunnel_alias("vm-1")
    assert result == "127.0.0.12"


def test_resolve_tunnel_alias_raises_when_not_registered():
    from lablink_allocator_service.client_session import RotationFailed
    from lablink_allocator_service.providers.connectivity.reverse_tunnel import (
        _resolve_tunnel_alias,
    )

    mock_db = type(
        "DB", (), {"get_tunnel_alias": staticmethod(lambda hostname: None)}
    )()
    with patch(
        "lablink_allocator_service.providers.connectivity.reverse_tunnel._db",
        return_value=mock_db,
    ):
        with pytest.raises(RotationFailed, match="vm-1"):
            _resolve_tunnel_alias("vm-1")


def test_make_join_material_returns_reverse_tunnel():
    from lablink_allocator_service.providers.connectivity.reverse_tunnel import (
        ReverseTunnelClientConnectivity,
    )

    c = ReverseTunnelClientConnectivity()
    m = c.make_join_material(
        allocator_url="http://a:5000",
        client_image="img:1",
        register_token="tk_1",
    )
    assert isinstance(m, ClientJoinMaterial)
    assert m.connectivity == "reverse_tunnel"
    assert m.allocator_url == "http://a:5000"
    assert m.client_image == "img:1"
    assert m.register_token == "tk_1"


def test_cleanup_client_identity_revokes_tunnel_client():
    from lablink_allocator_service.providers.connectivity.reverse_tunnel import (
        ReverseTunnelClientConnectivity,
    )

    with patch(
        "lablink_allocator_service.providers.connectivity.reverse_tunnel."
        "tunnel_manager.revoke_client"
    ) as m:
        c = ReverseTunnelClientConnectivity()
        c.cleanup_client_identity(hostname="vm-1")
    m.assert_called_once_with("vm-1")
