"""Select a ComputeProvider by name. First-party providers are discovered
via the `lablink.providers` entry-point group; built-in `aws` is always
available even if entry-point metadata is missing (editable installs)."""
from __future__ import annotations

import logging
from importlib.metadata import entry_points

from lablink_allocator_service.providers.aws import AWSProvider
from lablink_allocator_service.providers.manual import ManualProvider
from lablink_allocator_service.providers.connectivity.lan_direct import (
    LANDirectClientConnectivity,
)
from lablink_allocator_service.providers.connectivity.mesh_overlay import (
    MeshOverlayClientConnectivity,
)
from lablink_allocator_service.providers.protocol import ComputeProvider

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "aws"

# Built-in fallback so the allocator works in editable/test installs where
# entry-point metadata may not be regenerated.
_BUILTIN: dict[str, type] = {"aws": AWSProvider, "manual": ManualProvider}

# Connectivity choices selectable for the "manual" provider only. Not an
# entry-point-discovered registry (unlike _BUILTIN/providers) — this is a
# small, closed set for now; see the mesh-overlay design spec's Forward
# Path for how a second backend would slot in.
_CONNECTIVITY_BUILTIN: dict[str, type] = {
    "lan_direct": LANDirectClientConnectivity,
    "mesh_overlay": MeshOverlayClientConnectivity,
}


def _discover() -> dict[str, type]:
    found = dict(_BUILTIN)
    try:
        for ep in entry_points(group="lablink.providers"):
            try:
                found[ep.name] = ep.load()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "provider entry point %s failed to load: %s", ep.name, exc
                )
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("entry-point discovery failed: %s", exc)
    return found


def get_provider(
    name: str | None,
    *,
    region: str,
    terraform_dir: str,
    connectivity: str | None = None,
) -> ComputeProvider:
    name = name or DEFAULT_PROVIDER
    providers = _discover()
    cls = providers.get(name)
    if cls is None:
        raise ValueError(
            f"unknown provider '{name}'; available: {sorted(providers)}"
        )
    if name == "manual":
        conn_name = connectivity or "lan_direct"
        conn_cls = _CONNECTIVITY_BUILTIN.get(conn_name)
        if conn_cls is None:
            raise ValueError(
                f"unknown connectivity '{conn_name}'; "
                f"available: {sorted(_CONNECTIVITY_BUILTIN)}"
            )
        return cls(
            region=region,
            terraform_dir=terraform_dir,
            client_connectivity=conn_cls(),
        )
    return cls(region=region, terraform_dir=terraform_dir)
