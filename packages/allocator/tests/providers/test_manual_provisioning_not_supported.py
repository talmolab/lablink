"""ManualProvider raises ProvisioningNotSupported for lifecycle ops."""
import pytest
from lablink_allocator_service.providers.protocol import (
    ProvisioningNotSupported,
)
from lablink_allocator_service.providers.manual import ManualProvider


def test_provision_hosts_raises_not_supported():
    p = ManualProvider()
    with pytest.raises(ProvisioningNotSupported):
        p.provision_hosts(count=1, spec={})


def test_destroy_hosts_raises_not_supported():
    p = ManualProvider()
    with pytest.raises(ProvisioningNotSupported):
        p.destroy_hosts([])


def test_recover_hosts_raises_not_supported():
    p = ManualProvider()
    with pytest.raises(ProvisioningNotSupported):
        p.recover_hosts([])
