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
    sentinel = BrowserSessionTarget(upstream="10.0.0.9:6080")
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
            api_token="api",
        )
    assert out is sentinel
    m.assert_called_once_with(
        database="DB",
        hostname="vm-1",
        session_id=sid,
        browser_token="tok",
        api_token="api",
    )
