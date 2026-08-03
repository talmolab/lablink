"""Reverse-tunnel connectivity: browser -> allocator nginx -> client
KasmVNC, reached through a tunnel the client dials OUT to the allocator's
own HTTPS address and holds open. For clients that can neither accept
inbound connections nor run Tailscale.

The tunnel implementation is an internal detail; nothing in this module's
public shape names it. See tunnel_manager."""
from __future__ import annotations

from lablink_allocator_service import tunnel_manager
from lablink_allocator_service.client_session import (
    BrowserSessionTarget,
    RotationFailed,
    prepare_browser_session,
)
from lablink_allocator_service.providers.protocol import ClientJoinMaterial


def _db():
    from lablink_allocator_service import main

    return main.database


def _resolve_tunnel_alias(hostname: str) -> str:
    """Resolve *hostname*'s assigned loopback alias, for
    prepare_browser_session's fallback_fn extension point — the same hook
    MeshOverlayClientConnectivity uses, so client_session stays free of
    any tunnel-specific import.

    Returns a bare address with no port so prepare_browser_session's
    hardcoded :6080/:7070 land on this client's own bindings."""
    octet = _db().get_tunnel_alias(hostname)
    if octet is None:
        raise RotationFailed(f"no tunnel alias recorded for {hostname}")
    return f"127.0.0.{octet}"


class ReverseTunnelClientConnectivity:
    name = "reverse_tunnel"
    requires_tailscale_check = False
    requires_tunnel_check = True

    def prepare_browser_session(self, **kwargs) -> BrowserSessionTarget:
        kwargs.setdefault("fallback_fn", _resolve_tunnel_alias)
        return prepare_browser_session(**kwargs)

    def make_join_material(
        self,
        *,
        allocator_url: str,
        client_image: str,
        register_token: str,
    ) -> ClientJoinMaterial:
        return ClientJoinMaterial(
            register_token=register_token,
            allocator_url=allocator_url,
            connectivity=self.name,
            client_image=client_image,
        )

    def cleanup_client_identity(self, *, hostname: str) -> None:
        tunnel_manager.revoke_client(hostname)
