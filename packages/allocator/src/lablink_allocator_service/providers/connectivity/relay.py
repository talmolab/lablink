"""Relay connectivity: browser -> allocator nginx proxy -> client KasmVNC,
reached over an frp (Fast Reverse Proxy) tunnel the client dials out
through, instead of a routable LAN/VPC address or a Tailscale overlay.
The fallback of last resort when a client's network won't carry
Tailscale at all -- see the relay-client-connectivity design spec.

`frp` is an internal implementation detail; nothing in this module's
public shape (class name, provider_metadata keys) names it."""
from __future__ import annotations

from lablink_allocator_service import relay_manager
from lablink_allocator_service.client_session import (
    BrowserSessionTarget,
    RotationFailed,
    prepare_browser_session,
)
from lablink_allocator_service.providers.protocol import ClientJoinMaterial


def _db():
    from lablink_allocator_service import main

    return main.database


def _resolve_relay_alias(hostname: str) -> str:
    """Resolve *hostname*'s assigned loopback alias. Used as
    ``prepare_browser_session``'s ``fallback_fn`` -- same extension point
    ``MeshOverlayClientConnectivity``/``AllocatorProxiedClientConnectivity``
    already use for their own resolvers, so ``client_session`` stays free
    of any frp-specific import.

    Returns a bare address with no port, so ``prepare_browser_session``'s
    hardcoded ``:6080``/``:7070`` suffixes land on this client's own
    visitor bindings."""
    octet = _db().get_relay_alias(hostname)
    if octet is None:
        raise RotationFailed(f"no relay alias recorded for {hostname}")
    return f"127.0.0.{octet}"


class RelayClientConnectivity:
    name = "relay"
    requires_tailscale_check = False
    requires_frp_check = True

    def prepare_browser_session(self, **kwargs) -> BrowserSessionTarget:
        kwargs.setdefault("fallback_fn", _resolve_relay_alias)
        return prepare_browser_session(**kwargs)

    def make_join_material(
        self, *, allocator_url: str, client_image: str,
        register_token: str, hostname_hint: str | None = None,
    ) -> ClientJoinMaterial:
        return ClientJoinMaterial(
            register_token=register_token, allocator_url=allocator_url,
            connectivity=self.name, client_image=client_image,
        )

    def cleanup_client_identity(self, *, hostname: str) -> None:
        relay_manager.stop_visitor(hostname)
