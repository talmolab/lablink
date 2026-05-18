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


@dataclass
class ClientHandle:
    """Provider-supplied identifier for one client host."""

    id: str
    hostname: str
    provider_metadata: dict = field(default_factory=dict)


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

    def provision_hosts(self, count: int, spec: dict) -> list[ClientHandle]: ...
    def destroy_hosts(self, handles: list[ClientHandle]) -> None: ...
    # recover_hosts returns True iff every handle recycled OK
    def recover_hosts(self, handles: list[ClientHandle]) -> bool: ...
    def list_hosts(self) -> list[ClientHandle]: ...
