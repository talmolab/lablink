"""Provider abstraction package.

The allocator core speaks only to the contracts in `protocol.py`. The
compute backend is selected at startup via `registry.get_provider`.
"""
from lablink_allocator_service.providers.protocol import (  # noqa: F401
    BrowserSessionTarget,
    ClientConnectivity,
    ClientHandle,
    ComputeProvider,
    ProviderActionNotWired,
)
from lablink_allocator_service.providers.registry import (  # noqa: F401,E402
    DEFAULT_PROVIDER,
    get_provider,
)
