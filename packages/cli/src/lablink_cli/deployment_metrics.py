"""CLI-local cache for allocator deployment metrics (issue #317).

Stored on the operator's machine under ``~/.lablink/deployments/`` so that
metrics for failed deploys (or for already-destroyed allocators) survive.

Records start life with ``status="in_progress"`` and are promoted to
``success`` / ``failed`` by :func:`~lablink_cli.commands.deploy.run_deploy`.
Plan-confirmation cancels and Ctrl-C leave the file in ``in_progress``
indefinitely — use ``lablink cache-clear --deployments --stale`` to prune
just those, or ``--deployments`` to wipe the whole cache.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

DEPLOYMENTS_DIR = Path.home() / ".lablink" / "deployments"


@dataclass
class DeploymentMetrics:
    deployment_name: str
    region: Optional[str] = None
    template_version: Optional[str] = None
    ssl_enabled: Optional[bool] = None
    allocator_deploy_start_time: Optional[str] = None
    allocator_deploy_end_time: Optional[str] = None
    allocator_terraform_init_duration_seconds: Optional[float] = None
    allocator_terraform_plan_duration_seconds: Optional[float] = None
    allocator_terraform_apply_duration_seconds: Optional[float] = None
    allocator_health_check_duration_seconds: Optional[float] = None
    allocator_total_deployment_duration_seconds: Optional[float] = None
    status: str = "in_progress"
    error: Optional[str] = None


def _slugify_timestamp(dt: datetime) -> str:
    return dt.isoformat().replace(":", "-")


def cache_path_for(deployment_name: str, start_time: datetime) -> Path:
    return DEPLOYMENTS_DIR / f"{deployment_name}-{_slugify_timestamp(start_time)}.json"


def write_metrics(path: Path, metrics: DeploymentMetrics) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(asdict(metrics), indent=2, sort_keys=True))
    tmp.replace(path)


def load_all_metrics() -> list[dict]:
    if not DEPLOYMENTS_DIR.exists():
        return []
    out = []
    for p in sorted(DEPLOYMENTS_DIR.glob("*.json")):
        try:
            out.append(json.loads(p.read_text()))
        except json.JSONDecodeError:
            continue
    return out


@contextmanager
def phase_timer(
    metrics: DeploymentMetrics,
    field_name: str,
    path: Path,
) -> Iterator[None]:
    """Time a code block with monotonic clock; persist on exit (even on error)."""
    start = time.monotonic()
    try:
        yield
    finally:
        setattr(metrics, field_name, round(time.monotonic() - start, 3))
        write_metrics(path, metrics)
