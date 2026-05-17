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
            return BrowserSessionTarget(upstream="10.0.0.5:6080")

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

    assert isinstance(GoodConn(), ClientConnectivity)
    assert isinstance(GoodProvider(), ComputeProvider)
    assert not isinstance(object(), ComputeProvider)


def test_provider_action_not_wired_is_exception():
    assert issubclass(ProviderActionNotWired, Exception)
