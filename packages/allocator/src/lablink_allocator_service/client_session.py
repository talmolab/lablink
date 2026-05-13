"""Browser-session preparation against a client VM's agent.

Single responsibility: POST /api/session/start on the client agent so
the agent rotates KasmVNC's password to the allocator-generated value.
After this returns, the browser can be redirected to the client VM's
KasmVNC URL with the freshly-rotated credentials.

Wrapped in a helper (rather than inlined into /api/request_vm) so the
retry/timeout/backoff policy is in one place and so the assignment
handler can release the seat on failure rather than leaving a
half-assigned row in the DB.
"""
from __future__ import annotations

import logging
import time

import requests


logger = logging.getLogger(__name__)


# Single retry with a short backoff. KasmVNC's `kasmvncpasswd` rewrite
# is local I/O so it normally returns in tens of milliseconds; a retry
# only matters when the agent itself is restarting between
# /api/session/start and the SIGHUP-to-Xvnc reload step.
_RETRY_DELAY_SECONDS = 1.5
_REQUEST_TIMEOUT_SECONDS = 5.0


class RotationFailed(Exception):
    """The agent on the client VM could not rotate the KasmVNC password.

    Raised after the single retry has been exhausted. The caller is
    expected to release the just-claimed seat (so the VM goes back
    into the pool) and render an error page to the student so they
    can try again.
    """


def prepare_browser_session(
    *,
    hostname: str,
    agent_url: str,
    password: str,
    register_token: str,
    timeout: float = _REQUEST_TIMEOUT_SECONDS,
) -> None:
    """Rotate the KasmVNC password on the client agent.

    Args:
        hostname: The VM hostname, used only for log context.
        agent_url: Base URL of the agent — e.g. http://<private-ip>:7070.
        password: The new VNC password to install on the client.
        register_token: Bearer token the agent validates on incoming
            calls (REGISTER_TOKEN env var on the client side).
        timeout: HTTP timeout for the agent call.

    Raises:
        RotationFailed: After one retry, if the agent never returns 200.
    """
    url = f"{agent_url.rstrip('/')}/api/session/start"
    headers = {
        "Authorization": f"Bearer {register_token}",
        "Content-Type": "application/json",
    }
    payload = {"password": password}

    last_error: Exception | None = None
    for attempt in (1, 2):
        try:
            resp = requests.post(
                url, json=payload, headers=headers, timeout=timeout
            )
            resp.raise_for_status()
            return
        except requests.RequestException as exc:
            last_error = exc
            logger.warning(
                "Password rotation failed (attempt %d) for '%s' on '%s': %s",
                attempt,
                hostname,
                url,
                exc,
            )
            if attempt == 1:
                time.sleep(_RETRY_DELAY_SECONDS)

    raise RotationFailed(
        f"Could not rotate KasmVNC password on '{hostname}': {last_error}"
    )
