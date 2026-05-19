import pytest


def test_manual_provider_flags_and_connectivity():
    from lablink_allocator_service.providers.manual import ManualProvider
    from lablink_allocator_service.providers.connectivity.lan_direct import (
        LANDirectClientConnectivity,
    )
    p = ManualProvider(region=None, terraform_dir=None)
    assert p.name == "manual"
    assert p.can_provision_hosts is False
    assert p.can_destroy_hosts is False
    assert p.can_recover_hosts is False
    assert isinstance(p.client_connectivity, LANDirectClientConnectivity)


def test_manual_provider_lifecycle_raises():
    from lablink_allocator_service.providers.manual import ManualProvider
    p = ManualProvider()
    for call in (lambda: p.provision_hosts(1, {}),
                 lambda: p.destroy_hosts([]),
                 lambda: p.recover_hosts([])):
        with pytest.raises(NotImplementedError):
            call()


def test_manual_provider_connectivity_injectable():
    from lablink_allocator_service.providers.manual import ManualProvider
    sentinel = object()
    p = ManualProvider(client_connectivity=sentinel)
    assert p.client_connectivity is sentinel


def test_manual_provider_list_hosts_is_lan_agnostic(monkeypatch):
    from lablink_allocator_service.providers import manual as m
    from lablink_allocator_service.providers.protocol import ClientHandle
    seen = {}
    class _DB:
        def list_hosts_by_provider(self, provider):
            seen["p"] = provider
            return ["vm-1"]
    monkeypatch.setattr(m, "_db", lambda: _DB(), raising=False)
    p = m.ManualProvider()
    result = p.list_hosts()
    assert len(result) == 1
    h = result[0]
    assert isinstance(h, ClientHandle)
    assert h.id == "vm-1"
    assert h.hostname == "vm-1"
    assert h.provider_metadata == {}
    assert seen["p"] == "manual"
