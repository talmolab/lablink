"""Push the session-metrics summary to the allocator.

The pusher swallows network exceptions — the integrity story is the
allocator noticing we *stop* pushing, not any single POST. A 409 means
the row was sealed (e.g. destroy already ran); the caller may choose
to stop the agent.

A 200 response echoes the allocator's authoritative session-start
timestamp (the DB's SessionStartedAt, null when the seat is free); the
pusher writes it to the on-disk session anchor. That heals a lost
anchor — e.g. the container was recreated mid-session and /tmp went
with it — within one push interval: the monitoring loop re-anchors from
the file on its next tick. Rewriting an unchanged value is a no-op for
the loop, so this never causes reset oscillation.
"""

import logging
from dataclasses import asdict
from datetime import datetime

import requests

from lablink_client_service.monitoring.aggregator import SessionCounters
from lablink_client_service.session_anchor import write_anchor

logger = logging.getLogger(__name__)

POST_TIMEOUT_SECONDS = 5


def _serialise_counters(c: SessionCounters) -> dict:
    d = asdict(c)
    d["session_started_at"] = c.session_started_at.isoformat()
    return d


def push_summary(
    allocator_url: str,
    hostname: str,
    client_secret: str,
    counters: SessionCounters,
) -> int | None:
    """POST one summary. Returns the HTTP status code or None on network error."""
    body = _serialise_counters(counters)
    payload = {
        "session_started_at": body.pop("session_started_at"),
        "counters": body,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {client_secret}",
    }
    url = f"{allocator_url.rstrip('/')}/api/session-metrics/{hostname}"
    try:
        resp = requests.post(
            url=url,
            json=payload,
            headers=headers,
            timeout=POST_TIMEOUT_SECONDS,
        )
    except requests.exceptions.RequestException as e:
        logger.debug("session-metrics push failed: %s", e)
        return None
    if resp.status_code >= 400:
        logger.warning(
            "session-metrics POST returned %s: %s",
            resp.status_code,
            resp.text[:200],
        )
    elif resp.status_code == 200:
        _adopt_echoed_anchor(resp)
    return resp.status_code


def _adopt_echoed_anchor(resp) -> None:
    """Write the allocator-echoed session start to the anchor file.

    Silently does nothing when the response carries no parseable
    ISO-8601 `session_started_at` (unassigned seat echoes null; older
    allocators echo nothing).
    """
    try:
        echoed = resp.json().get("session_started_at")
    except Exception:
        return
    if not isinstance(echoed, str):
        return
    try:
        write_anchor(datetime.fromisoformat(echoed))
    except (ValueError, OSError):
        logger.debug("Could not adopt echoed session anchor: %r", echoed)
