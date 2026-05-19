"""ManualProvider — BYO hosts the instructor registers; LabLink never
provisions/destroys/recovers them. LAN-agnostic: LAN lives only in the
injected ClientConnectivity, never here."""
from __future__ import annotations

from lablink_allocator_service.providers.connectivity.lan_direct import (
    LANDirectClientConnectivity,
)
from lablink_allocator_service.providers.protocol import ClientHandle


def _db():
    from lablink_allocator_service import main
    return main.database


class ManualProvider:
    name = "manual"
    can_provision_hosts = False
    can_destroy_hosts = False
    can_recover_hosts = False

    def __init__(self, *, region=None, terraform_dir=None,
                 client_connectivity=None, **_):
        self.client_connectivity = (
            client_connectivity
            if client_connectivity is not None
            else LANDirectClientConnectivity()
        )

    def provision_hosts(self, count, spec):
        raise NotImplementedError(
            "ManualProvider doesn't provision — instructor brings the "
            "machines. Use 'lablink launch' for the registration command."
        )

    def destroy_hosts(self, handles):
        raise NotImplementedError(
            "ManualProvider cannot destroy BYO machines."
        )

    def recover_hosts(self, handles):
        raise NotImplementedError(
            "ManualProvider cannot recover BYO machines; the box rejoins "
            "via docker --restart + idempotent re-registration."
        )

    def list_hosts(self):
        return [
            ClientHandle(id=h, hostname=h)
            for h in _db().list_hosts_by_provider(self.name)
        ]
