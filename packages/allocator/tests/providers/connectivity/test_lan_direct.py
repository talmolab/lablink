import uuid


def test_make_join_material_lan_direct():
    from lablink_allocator_service.providers.connectivity.lan_direct import (
        LANDirectClientConnectivity,
    )
    c = LANDirectClientConnectivity()
    jm = c.make_join_material(allocator_url="http://a:5000",
                              client_image="img:1", register_token="tk")
    assert jm.connectivity == "lan_direct"
    assert jm.allocator_url == "http://a:5000"
    assert jm.client_image == "img:1"
    assert jm.register_token == "tk"


def test_prepare_browser_session_lan_direct(monkeypatch):
    import lablink_allocator_service.client_session as cs
    from lablink_allocator_service.providers.connectivity.lan_direct import (
        LANDirectClientConnectivity,
    )
    posted = {}
    monkeypatch.setattr(cs, "_post_rotate",
                        lambda url, body, *, bearer: posted.update(
                            url=url, body=body, bearer=bearer))
    executed = {}
    class _Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params):
            executed["sql"] = sql
            executed["params"] = params
    class _DB:
        table_name = "vms"
        _cursor = _Cur()
        def get_lan_ip(self, hostname): return "10.0.0.9"

    t = LANDirectClientConnectivity().prepare_browser_session(
        database=_DB(), hostname="vm-1", session_id=uuid.uuid4(),
        browser_token="btok", agent_token="agenttok",
    )
    assert t.ws_url == "ws://10.0.0.9:6080"
    assert t.browser_credential and t.browser_credential == posted["body"]["password"]
    # RFB VncAuth caps at 8 chars; longer passwords would be silently
    # truncated by KasmVNC, leaving the page's credential the wrong size.
    assert len(t.browser_credential) == 8
    assert posted["url"] == "http://10.0.0.9:7070/api/session/start"
    assert posted["bearer"] == "agenttok"
    assert "browser_ws_url" in executed["sql"]
    assert "browser_credential" in executed["sql"]
