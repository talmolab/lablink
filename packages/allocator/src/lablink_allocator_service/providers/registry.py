"""Select a ComputeProvider by name. First-party providers are discovered
via the `lablink.providers` entry-point group; built-in `aws` is always
available even if entry-point metadata is missing (editable installs)."""
from __future__ import annotations

import logging
from importlib.metadata import entry_points

from lablink_allocator_service.providers.aws import AWSProvider
from lablink_allocator_service.providers.manual import ManualProvider
from lablink_allocator_service.providers.protocol import ComputeProvider

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "aws"

# Built-in fallback so the allocator works in editable/test installs where
# entry-point metadata may not be regenerated.
_BUILTIN: dict[str, type] = {"aws": AWSProvider, "manual": ManualProvider}


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
    name: str | None, *, region: str, terraform_dir: str
) -> ComputeProvider:
    name = name or DEFAULT_PROVIDER
    providers = _discover()
    cls = providers.get(name)
    if cls is None:
        raise ValueError(
            f"unknown provider '{name}'; available: {sorted(providers)}"
        )
    return cls(region=region, terraform_dir=terraform_dir)
