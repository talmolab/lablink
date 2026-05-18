"""AWS connectivity: browser -> allocator nginx proxy -> client KasmVNC.

PR B is behavior-preserving: this delegates verbatim to the existing
client_session.prepare_browser_session (kwargs-only signature preserved)."""
from __future__ import annotations

from lablink_allocator_service.client_session import (
    BrowserSessionTarget,
    prepare_browser_session,
)


class AllocatorProxiedClientConnectivity:
    name = "allocator_proxied"

    def prepare_browser_session(self, **kwargs) -> BrowserSessionTarget:
        return prepare_browser_session(**kwargs)
