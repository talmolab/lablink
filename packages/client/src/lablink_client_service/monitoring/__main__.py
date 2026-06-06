"""Tier 1 monitoring agent entry point.

Reads its config from a JSON file at the path in $LABLINK_MONITORING_CONFIG
(written by start.sh from the registration response). Samples every
`sample_interval_seconds`, pushes every `push_interval_seconds`, and on
SIGTERM does a final flush before exiting.
"""

import json
import logging
import os
import signal
import threading
from datetime import datetime, timezone

from lablink_client_service.monitoring.aggregator import (
    Sample,
    SessionCounters,
    apply_sample,
    new_counters,
)
from lablink_client_service.monitoring.pusher import push_summary
from lablink_client_service.monitoring.samplers.active_window import (
    sample as _sample_active_window,
)
from lablink_client_service.monitoring.samplers.filesystem import (
    sample as _sample_filesystem,
)
from lablink_client_service.monitoring.samplers.gpu import (
    sample as _sample_gpu,
)
from lablink_client_service.monitoring.samplers.processes import (
    sample as _sample_processes,
)

logger = logging.getLogger(__name__)

_stop_event = threading.Event()
_counters: SessionCounters | None = None
_cfg: dict = {}


def _handle_sigterm(_signum, _frame) -> None:
    logger.info("Monitoring agent: SIGTERM received, flushing")
    _flush_final()
    _stop_event.set()


def _flush_final() -> None:
    if _counters is None:
        return
    try:
        push_summary(
            allocator_url=_cfg["allocator_url"],
            hostname=_cfg["hostname"],
            client_secret=_cfg["client_secret"],
            counters=_counters,
        )
    except Exception:
        logger.exception("Final flush failed")


def _read_config() -> dict:
    path = os.environ.get(
        "LABLINK_MONITORING_CONFIG", "/tmp/lablink-monitoring.json"
    )
    with open(path) as f:
        return json.load(f)


def _resolve_subject_patterns(cfg: dict) -> list[str]:
    """Use explicit patterns when present, else fall back to client.software."""
    patterns = list(cfg.get("subject_window_patterns") or [])
    if patterns:
        return patterns
    software = cfg.get("client_software")
    return [software] if software else []


def _tick(cfg: dict, counters: SessionCounters) -> None:
    ts = datetime.now(timezone.utc)
    bucket = _sample_active_window(subject_patterns=_resolve_subject_patterns(cfg))
    util, vram = _sample_gpu()
    procs = _sample_processes(allowlist=cfg["process_allowlist"])
    frames, epoch, loss = _sample_filesystem(watch_dir=cfg["watch_dir"])
    apply_sample(
        counters,
        Sample(
            ts=ts,
            sample_interval_seconds=cfg["sample_interval_seconds"] or 2,
            active_window_bucket=bucket,
            gpu_util_pct=util,
            vram_mb=vram,
            processes_seen=procs,
            max_labeled_frames=frames,
            training_epochs_completed=epoch,
            training_final_loss=loss,
        ),
    )


def main() -> None:
    global _counters, _cfg
    _cfg = _read_config()
    _counters = new_counters(session_started_at=datetime.now(timezone.utc))

    # signal.signal can only be called from the main thread; in tests we
    # launch main() on a background thread, so guard.
    try:
        signal.signal(signal.SIGTERM, _handle_sigterm)
        signal.signal(signal.SIGINT, _handle_sigterm)
    except ValueError:
        logger.debug("Skipping signal handler registration (not on main thread)")

    sample_int = _cfg["sample_interval_seconds"]
    push_int = _cfg["push_interval_seconds"]
    last_push = 0.0
    elapsed = 0.0

    logger.info(
        "Monitoring agent started (sample=%ss push=%ss)",
        sample_int,
        push_int,
    )
    while not _stop_event.is_set():
        try:
            _tick(_cfg, _counters)
        except Exception:
            logger.exception("Sampler tick failed; continuing")
        elapsed += sample_int
        if elapsed - last_push >= push_int:
            try:
                push_summary(
                    allocator_url=_cfg["allocator_url"],
                    hostname=_cfg["hostname"],
                    client_secret=_cfg["client_secret"],
                    counters=_counters,
                )
                last_push = elapsed
            except Exception:
                logger.exception("Push failed; will retry next interval")
        _stop_event.wait(sample_int)


if __name__ == "__main__":
    main()
