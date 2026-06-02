from lablink_allocator_service.providers.protocol import (
    ClientHandle,
    ComputeProvider,
    ClientConnectivity,
    ProviderActionNotWired,
    BrowserSessionTarget,
)


def test_client_handle_fields():
    h = ClientHandle(id="i-123", hostname="vm-1", provider_metadata={"region": "us-west-2"})
    assert h.id == "i-123"
    assert h.hostname == "vm-1"
    assert h.provider_metadata["region"] == "us-west-2"


def test_browser_session_target_is_reexported_singleton():
    # protocol must re-export the SAME class client_session uses, so there
    # is exactly one BrowserSessionTarget type in the codebase.
    from lablink_allocator_service.client_session import (
        BrowserSessionTarget as CsTarget,
    )

    assert BrowserSessionTarget is CsTarget


def test_protocols_are_runtime_checkable():
    class GoodConn:
        name = "allocator_proxied"

        def prepare_browser_session(self, **kwargs):
            return BrowserSessionTarget(ws_url="proxy/tok", browser_credential=None)

        def make_join_material(self, **kwargs): ...

    class GoodProvider:
        name = "aws"
        client_connectivity = GoodConn()
        can_provision_hosts = True
        can_destroy_hosts = True
        can_recover_hosts = True

        def provision_hosts(self, count, spec): ...
        def destroy_hosts(self, handles): ...
        def recover_hosts(self, handles): ...
        def list_hosts(self): return []
        def get_host_access(self, hostname): return (None, None, None)

    assert isinstance(GoodConn(), ClientConnectivity)
    assert isinstance(GoodProvider(), ComputeProvider)
    assert not isinstance(object(), ComputeProvider)


def test_provider_action_not_wired_is_exception():
    assert issubclass(ProviderActionNotWired, Exception)


def test_client_join_material_fields():
    from lablink_allocator_service.providers.protocol import ClientJoinMaterial

    m = ClientJoinMaterial(
        register_token="tk_x",
        allocator_url="http://a:5000",
        connectivity="allocator_proxied",
        client_image="ghcr.io/x/client:latest",
    )
    assert m.register_token == "tk_x"
    assert m.allocator_url == "http://a:5000"
    assert m.connectivity == "allocator_proxied"
    assert m.client_image == "ghcr.io/x/client:latest"


def test_client_connectivity_protocol_requires_make_join_material():
    from lablink_allocator_service.providers.protocol import ClientConnectivity

    class Missing:
        name = "x"

        def prepare_browser_session(self, **kwargs):
            ...

    class Complete:
        name = "x"

        def prepare_browser_session(self, **kwargs):
            ...

        def make_join_material(self, **kwargs):
            ...

    assert not isinstance(Missing(), ClientConnectivity)
    assert isinstance(Complete(), ClientConnectivity)
