"""Mesh-overlay connectivity: browser -> allocator nginx proxy -> client
KasmVNC, reached over a Tailscale overlay instead of a routable LAN/VPC
address. Not Run:AI-specific — any client that isn't on the allocator's
own network fits this connectivity strategy; Run:AI-hosted client
workloads are simply the motivating case."""
from __future__ import annotations

from lablink_allocator_service.client_session import (
    BrowserSessionTarget,
    RotationFailed,
    prepare_browser_session,
)
from lablink_allocator_service.providers.protocol import ClientJoinMaterial
from lablink_allocator_service.get_config import get_config


def _db():
    from lablink_allocator_service import main

    return main.database


def _resolve_overlay_host(hostname: str) -> str:
    """Resolve *hostname*'s registered overlay hostname to its Tailscale
    MagicDNS name. Used as ``prepare_browser_session``'s ``fallback_fn`` —
    same extension point ``AllocatorProxiedClientConnectivity`` uses for
    its EC2-private-IP fallback, so ``client_session`` stays free of any
    Tailscale-specific import."""
    overlay_hostname = _db().get_overlay_hostname(hostname)
    if not overlay_hostname:
        raise RotationFailed(f"no overlay hostname recorded for {hostname}")
    tailnet = get_config().manual.overlay_tailnet
    if not tailnet:
        raise RotationFailed(
            f"manual.overlay_tailnet is not configured; cannot resolve "
            f"overlay hostname for {hostname}"
        )
    return f"{overlay_hostname}.{tailnet}"


class MeshOverlayClientConnectivity:
    name = "mesh_overlay"
    requires_tailscale_check = True

    def prepare_browser_session(self, **kwargs) -> BrowserSessionTarget:
        kwargs.setdefault("fallback_fn", _resolve_overlay_host)
        return prepare_browser_session(**kwargs)

    def make_join_material(
        self,
        *,
        allocator_url: str,
        client_image: str,
        register_token: str,
        hostname_hint: str | None = None,
    ) -> ClientJoinMaterial:
        return ClientJoinMaterial(
            register_token=register_token,
            allocator_url=allocator_url,
            connectivity=self.name,
            client_image=client_image,
        )
