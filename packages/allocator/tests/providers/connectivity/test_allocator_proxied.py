import uuid
from unittest.mock import patch

from lablink_allocator_service.providers.connectivity.allocator_proxied import (
    AllocatorProxiedClientConnectivity,
)
from lablink_allocator_service.providers.protocol import (
    ClientConnectivity,
    BrowserSessionTarget,
)


def test_satisfies_protocol_and_name():
    conn = AllocatorProxiedClientConnectivity()
    assert isinstance(conn, ClientConnectivity)
    assert conn.name == "allocator_proxied"


def test_delegates_to_client_session_unchanged():
    sentinel = BrowserSessionTarget(ws_url="proxy/tok", browser_credential=None)
    sid = uuid.uuid4()
    with patch(
        "lablink_allocator_service.providers.connectivity.allocator_proxied."
        "prepare_browser_session",
        return_value=sentinel,
    ) as m:
        conn = AllocatorProxiedClientConnectivity()
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
    )


def test_make_join_material_returns_allocator_proxied():
    from lablink_allocator_service.providers.connectivity.allocator_proxied import (
        AllocatorProxiedClientConnectivity,
    )
    from lablink_allocator_service.providers.protocol import ClientJoinMaterial

    c = AllocatorProxiedClientConnectivity()
    m = c.make_join_material(
        allocator_url="http://a:5000",
        client_image="img:1",
        register_token="tk_1",
    )
    assert isinstance(m, ClientJoinMaterial)
    assert m.connectivity == "allocator_proxied"
    assert m.allocator_url == "http://a:5000"
    assert m.client_image == "img:1"
    assert m.register_token == "tk_1"
