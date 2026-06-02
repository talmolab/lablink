"""Provider contracts. Behavior-preserving: BrowserSessionTarget is the
exact dataclass client_session already returns (re-exported, not redefined)
so routes/internal_proxy_auth.py and existing tests are unaffected."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from lablink_allocator_service.client_session import (  # single canonical type
    BrowserSessionTarget as BrowserSessionTarget,
)


class ProviderActionNotWired(Exception):
    """Raised by a provider method that is part of the contract but is
    intentionally not wired into the allocator core in this PR."""


class ProvisioningNotSupported(Exception):
    """Raised by a provider whose structural model does not support a
    lifecycle operation — distinct from `ProviderActionNotWired` (deferred
    wiring). For example, `ManualProvider` cannot ever provision hosts
    because the operator brings them; raising this signals "never" rather
    than "not yet"."""


@dataclass
class ClientHandle:
    """Provider-supplied identifier for one client host."""

    id: str
    hostname: str
    provider_metadata: dict = field(default_factory=dict)


@dataclass
class ProvisionResult:
    """Result of provider.provision_hosts(...).

    Returned by AWSProvider.provision_hosts and consumed by the
    /api/launch route handler in main.py.
    """

    handles: list[ClientHandle]
    timings: dict[str, dict]  # hostname -> {start_time, end_time, seconds}
    apply_stdout: str  # ANSI-stripped Terraform apply output


@dataclass
class DestroyResult:
    """Result of provider.destroy_hosts(...)."""

    stdout: str  # ANSI-stripped Terraform destroy output


@dataclass
class ClientJoinMaterial:
    """Everything a fresh client needs to bootstrap (SR-F13). Note:
    client_secret is minted by the registration endpoint, NOT carried here."""

    register_token: str
    allocator_url: str
    connectivity: str
    client_image: str


@runtime_checkable
class ClientConnectivity(Protocol):
    """Provider-owned strategy for browser -> client KasmVNC reachability."""

    name: str

    def prepare_browser_session(self, **kwargs) -> BrowserSessionTarget: ...

    def make_join_material(self, **kwargs) -> ClientJoinMaterial: ...


@runtime_checkable
class ComputeProvider(Protocol):
    name: str
    client_connectivity: ClientConnectivity
    can_provision_hosts: bool
    can_destroy_hosts: bool
    can_recover_hosts: bool

    def provision_hosts(self, count: int, spec: dict) -> ProvisionResult: ...
    def destroy_hosts(self, handles: list[ClientHandle]) -> DestroyResult: ...
    # recover_hosts returns True iff every handle recycled OK
    def recover_hosts(self, handles: list[ClientHandle]) -> bool: ...
    def list_hosts(self) -> list[ClientHandle]: ...
    def get_host_access(
        self, hostname: str
    ) -> tuple[str | None, str | None, str | None]:
        """Return (instance_id, public_ip, ssh_key_path) for *hostname*.

        Any component may be None if unavailable (no credentials, not
        reachable, etc.).  Providers that cannot recover hosts should
        return (None, None, None) — ``_reboot_vm`` gates on
        ``can_recover_hosts`` before calling this, so it will only ever
        be invoked on capable providers.
        """
        ...
