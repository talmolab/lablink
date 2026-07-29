import uuid
from unittest.mock import patch

from lablink_allocator_service.providers.protocol import (
    ClientConnectivity,
    BrowserSessionTarget,
)


def test_satisfies_protocol_and_name():
    from lablink_allocator_service.providers.connectivity.relay import (
        RelayClientConnectivity,
    )

    conn = RelayClientConnectivity()
    assert isinstance(conn, ClientConnectivity)
    assert conn.name == "relay"
    assert conn.requires_tailscale_check is False
    assert conn.requires_frp_check is True


def test_delegates_to_client_session_with_relay_fallback():
    from lablink_allocator_service.providers.connectivity.relay import (
        RelayClientConnectivity,
        _resolve_relay_alias,
    )

    sentinel = BrowserSessionTarget(ws_url="proxy/tok", browser_credential=None)
    sid = uuid.uuid4()
    with patch(
        "lablink_allocator_service.providers.connectivity.relay."
        "prepare_browser_session",
        return_value=sentinel,
    ) as m:
        conn = RelayClientConnectivity()
        out = conn.prepare_browser_session(
            database="DB", hostname="vm-1", session_id=sid,
            browser_token="tok", agent_token="api",
        )
    assert out is sentinel
    m.assert_called_once_with(
        database="DB", hostname="vm-1", session_id=sid,
        browser_token="tok", agent_token="api",
        fallback_fn=_resolve_relay_alias,
    )


def test_resolve_relay_alias_builds_loopback_address():
    from lablink_allocator_service.providers.connectivity.relay import (
        _resolve_relay_alias,
    )

    mock_db = type("DB", (), {"get_relay_alias": staticmethod(
        lambda hostname: 12
    )})()

    with patch(
        "lablink_allocator_service.providers.connectivity.relay._db",
        return_value=mock_db,
    ):
        result = _resolve_relay_alias("vm-1")
    assert result == "127.0.0.12"


def test_resolve_relay_alias_raises_when_not_registered():
    from lablink_allocator_service.client_session import RotationFailed
    from lablink_allocator_service.providers.connectivity.relay import (
        _resolve_relay_alias,
    )

    mock_db = type("DB", (), {"get_relay_alias": staticmethod(lambda hostname: None)})()

    with patch(
        "lablink_allocator_service.providers.connectivity.relay._db",
        return_value=mock_db,
    ):
        try:
            _resolve_relay_alias("vm-1")
            assert False, "expected RotationFailed"
        except RotationFailed as e:
            assert "vm-1" in str(e)


def test_make_join_material_returns_relay():
    from lablink_allocator_service.providers.connectivity.relay import (
        RelayClientConnectivity,
    )
    from lablink_allocator_service.providers.protocol import ClientJoinMaterial

    c = RelayClientConnectivity()
    m = c.make_join_material(
        allocator_url="http://a:5000", client_image="img:1",
        register_token="tk_1",
    )
    assert isinstance(m, ClientJoinMaterial)
    assert m.connectivity == "relay"
    assert m.allocator_url == "http://a:5000"
    assert m.client_image == "img:1"
    assert m.register_token == "tk_1"


def test_cleanup_client_identity_stops_visitor():
    from lablink_allocator_service.providers.connectivity.relay import (
        RelayClientConnectivity,
    )

    with patch(
        "lablink_allocator_service.providers.connectivity.relay.relay_manager"
    ) as mock_manager:
        RelayClientConnectivity().cleanup_client_identity(hostname="vm-1")
    mock_manager.stop_visitor.assert_called_once_with("vm-1")
