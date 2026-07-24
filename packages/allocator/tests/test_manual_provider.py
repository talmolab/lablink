import pytest
from unittest.mock import MagicMock

from lablink_allocator_service.providers.manual import ManualProvider
from lablink_allocator_service.providers.protocol import (
    ProvisioningNotSupported,
)


def test_provision_hosts_ignores_progress_callback():
    provider = ManualProvider()
    callback = MagicMock()
    with pytest.raises(ProvisioningNotSupported):
        provider.provision_hosts(count=1, spec={}, progress_callback=callback)
    callback.assert_not_called()


def test_destroy_hosts_ignores_progress_callback():
    provider = ManualProvider()
    callback = MagicMock()
    with pytest.raises(ProvisioningNotSupported):
        provider.destroy_hosts([], progress_callback=callback)
    callback.assert_not_called()
