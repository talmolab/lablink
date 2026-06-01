"""Per-session preparation: rotate the VNC password on the assigned
client and persist per-session state on the clients row.

Called from /api/request_vm inside the seat-assignment transaction so
rotation failure rolls back the assignment.
"""
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Callable

import requests


ROTATE_TIMEOUT = 5.0
ROTATE_BACKOFF_SECONDS = 1.5


class RotationFailed(RuntimeError):
    """Raised when the per-session password rotation cannot be completed."""


@dataclass
class BrowserSessionTarget:
    ws_url: str                       # opaque URL the page opens
    browser_credential: str | None    # non-None ⇒ page sends HTTP Basic


def _lookup_private_ip(
    hostname: str,
    database=None,
    *,
    fallback_fn: Callable[[str], str] | None = None,
) -> str:
    """Return the private IP for *hostname*.

    Resolution order:
    1. ``database.get_lan_ip(hostname)`` — present for BYO/manual rows that
       record their LAN IP at registration time.
    2. ``fallback_fn(hostname)`` — caller-supplied resolver (e.g. EC2 tag
       lookup).  When omitted, falls through to step 3.
    3. Raises :exc:`RotationFailed` with a descriptive message.

    The fallback is intentionally not hard-coded here so that
    ``client_session`` has no dependency on AWS utilities.  Provider-specific
    connectivity strategies (e.g. ``AllocatorProxiedClientConnectivity``) pass
    their own resolver via :func:`prepare_browser_session`.
    """
    if database is not None:
        stored = database.get_lan_ip(hostname)
        if stored:
            return stored
    if fallback_fn is not None:
        return fallback_fn(hostname)
    raise RotationFailed(
        f"no IP recorded for {hostname} and no fallback resolver provided"
    )


def _post_rotate(url: str, body: dict, *, bearer: str) -> None:
    last_exc = None
    for attempt in range(2):  # initial + one retry
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {bearer}"},
                json=body,
                timeout=ROTATE_TIMEOUT,
            )
            resp.raise_for_status()
            return
        except requests.RequestException as exc:
            last_exc = exc
            if attempt == 0:
                time.sleep(ROTATE_BACKOFF_SECONDS)
    raise RotationFailed(str(last_exc))


def prepare_browser_session(
    *,
    database,
    hostname: str,
    session_id: uuid.UUID,
    browser_token: str,
    agent_token: str,
    fallback_fn: Callable[[str], str] | None = None,
) -> BrowserSessionTarget:
    """Rotate the assigned client's VNC password and persist per-session
    columns on the VM row. Must be called inside the seat-assignment
    transaction so failures roll back.

    `agent_token` is the deployment agent-control token (`main.AGENT_TOKEN`);
    the client agent receives the same value as its AGENT_TOKEN env via the
    Terraform user_data and validates it on every /api/session/start call.
    Passed explicitly rather than read from env so this function has no
    hidden global dependency for tests.

    `fallback_fn` is an optional callable ``(hostname: str) -> str`` that
    resolves the private IP when no stored LAN IP is found in the database.
    Provider-specific connectivity strategies supply this (e.g.
    ``AllocatorProxiedClientConnectivity`` passes an EC2 tag lookup).
    When omitted and no stored IP exists, :exc:`RotationFailed` is raised.
    """
    private_ip = _lookup_private_ip(hostname, database, fallback_fn=fallback_fn)
    password = secrets.token_urlsafe(24)
    upstream = f"{private_ip}:6080"

    # Body shape matches the agent's contract (packages/client/.../agent/api.py):
    # a single `password` field. session_id and browser_token are bookkeeping
    # the *allocator* persists in its own DB; the agent doesn't need either.
    _post_rotate(
        f"http://{private_ip}:7070/api/session/start",
        {"password": password},
        bearer=agent_token,
    )

    ws_url = f"proxy/{browser_token}"
    with database._cursor as cursor:
        cursor.execute(
            f"UPDATE {database.table_name} "
            f"SET sessionid = %s, "
            f"    browsertoken = %s, "
            f"    vncpassword = %s, "
            f"    upstream = %s, "
            f"    browser_ws_url = %s, "
            f"    browser_credential = NULL, "
            f"    sessionstartedat = NOW() "
            f"WHERE hostname = %s",
            (str(session_id), browser_token, password, upstream,
             ws_url, hostname),
        )

    return BrowserSessionTarget(ws_url=ws_url, browser_credential=None)
