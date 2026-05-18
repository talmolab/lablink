"""AWS connectivity: browser -> allocator nginx proxy -> client KasmVNC."""
from __future__ import annotations

from lablink_allocator_service.client_session import (
    BrowserSessionTarget,
    prepare_browser_session,
)
from lablink_allocator_service.providers.protocol import ClientJoinMaterial


class AllocatorProxiedClientConnectivity:
    name = "allocator_proxied"

    def prepare_browser_session(self, **kwargs) -> BrowserSessionTarget:
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
