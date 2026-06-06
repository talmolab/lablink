"""Push the session-metrics summary to the allocator.

The pusher swallows network exceptions — the integrity story is the
allocator noticing we *stop* pushing, not any single POST. A 409 means
the row was sealed (e.g. destroy already ran); the caller may choose
to stop the agent.
"""

import logging
from dataclasses import asdict

import requests

from lablink_client_service.monitoring.aggregator import SessionCounters

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
    return resp.status_code
