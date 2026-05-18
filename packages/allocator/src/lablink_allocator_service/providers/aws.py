"""AWSProvider — behavior-preserving wrapper over existing AWS utilities.

PR B scope: `recover_hosts` and `client_connectivity` are wired into the
core; `list_hosts` reads Terraform state; `provision_hosts`/`destroy_hosts`
remain inline in main.py for now (raise ProviderActionNotWired)."""
from __future__ import annotations

from lablink_allocator_service.providers.connectivity.allocator_proxied import (
    AllocatorProxiedClientConnectivity,
)
from lablink_allocator_service.providers.protocol import (
    ClientHandle,
    ProviderActionNotWired,
)
from lablink_allocator_service.utils.aws_utils import stop_start_ec2_instance
from lablink_allocator_service.utils.terraform_utils import (
    get_instance_ids,
    get_instance_names,
)


class AWSProvider:
    name = "aws"
    can_provision_hosts = True
    can_destroy_hosts = True
    can_recover_hosts = True

    def __init__(self, *, region: str, terraform_dir: str):
        self._region = region
        self._terraform_dir = terraform_dir
        self.client_connectivity = AllocatorProxiedClientConnectivity()

    def recover_hosts(self, handles: list[ClientHandle]) -> bool:
        # Verbatim of reboot.py's EC2 fallback: stop_start_ec2_instance.
        # Returns True iff EVERY recycle succeeded — the caller
        # (reboot.py) uses this to decide record_reboot vs error log,
        # so failure must NOT masquerade as success.
        all_ok = True
        for h in handles:
            region = h.provider_metadata.get("region", self._region)
            if not stop_start_ec2_instance(h.id, region=region):
                all_ok = False
        return all_ok

    def list_hosts(self) -> list[ClientHandle]:
        ids = get_instance_ids(terraform_dir=self._terraform_dir)
        names = get_instance_names(terraform_dir=self._terraform_dir)
        return [
            ClientHandle(id=i, hostname=n, provider_metadata={"region": self._region})
            for i, n in zip(ids, names)
        ]

    def provision_hosts(self, count: int, spec: dict) -> list[ClientHandle]:
        raise ProviderActionNotWired(
            "AWSProvider.provision_hosts is not wired in PR B; Terraform "
            "apply stays inline in main.launch() until PR D."
        )

    def destroy_hosts(self, handles: list[ClientHandle]) -> None:
        raise ProviderActionNotWired(
            "AWSProvider.destroy_hosts is not wired in PR B; Terraform "
            "destroy stays inline in main.destroy() until PR D."
        )
