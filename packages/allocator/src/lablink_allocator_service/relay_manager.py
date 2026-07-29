"""Process lifecycle for the relay connectivity's two frp roles.

`frps` (the always-on tunnel server relay clients' `frpc` dial into) is
started once by start.sh, not by this module -- this module only reports
on its liveness (frp_status, for /api/health). What this module DOES own
is the per-client `frpc`-visitor subprocess: each relay-connected client
gets its own dedicated `frpc` process running purely in visitor mode,
pulling that one client's two STCP proxies (KasmVNC :6080, agent :7070)
down to its assigned loopback alias so nginx can dial them exactly like
any other connectivity's "private IP" -- see the relay-client-connectivity
design spec for the full rationale.

One subprocess per client (rather than one shared frpc with N
dynamically-reloaded [[visitors]] blocks) avoids relying on frp's
config-reload command being race-free under concurrent registrations.

No interface setup is needed for the loopback aliases: Linux binds the
whole 127.0.0.0/8 to `lo`, so 127.0.0.<n> is already locally bindable
without an `ip addr add`.
"""
from __future__ import annotations

import socket
import subprocess
from pathlib import Path

from lablink_allocator_service.get_config import get_config

VISITOR_CONFIG_DIR = Path("/tmp/lablink-frp-visitors")

# client_id -> subprocess.Popen, so a later stop_visitor() can find and
# terminate the right process. Module-level: there is exactly one
# allocator process per deployment, matching how other per-deployment
# in-memory state (e.g. the secret-hash cache in secret_hash.py) is
# already modeled.
_visitors: dict[str, subprocess.Popen] = {}


def _visitor_config_path(client_id: str) -> Path:
    return VISITOR_CONFIG_DIR / f"{client_id}.toml"


def _visitor_config_toml(
    *, client_id: str, alias_octet: int, secret_key: str,
    server_addr: str, server_port: int,
) -> str:
    alias = f"127.0.0.{alias_octet}"
    return (
        f'serverAddr = "{server_addr}"\n'
        f"serverPort = {server_port}\n"
        "\n"
        "[[visitors]]\n"
        f'name = "{client_id}-kasmvnc-visitor"\n'
        'type = "stcp"\n'
        f'serverName = "{client_id}-kasmvnc"\n'
        f'secretKey = "{secret_key}"\n'
        f'bindAddr = "{alias}"\n'
        "bindPort = 6080\n"
        "\n"
        "[[visitors]]\n"
        f'name = "{client_id}-agent-visitor"\n'
        'type = "stcp"\n'
        f'serverName = "{client_id}-agent"\n'
        f'secretKey = "{secret_key}"\n'
        f'bindAddr = "{alias}"\n'
        "bindPort = 7070\n"
    )


def start_visitor(
    *, client_id: str, alias_octet: int, secret_key: str,
    server_addr: str, server_port: int,
) -> None:
    """Spawn this client's dedicated frpc-visitor subprocess.

    Idempotent for a *live* visitor: an already-running visitor for this
    client_id is left alone (re-registration is expected to reuse the same
    alias/secret rather than churn the subprocess). A tracked-but-dead
    visitor is replaced.
    """
    running = _visitors.get(client_id)
    if running is not None and running.poll() is None:
        return
    VISITOR_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config_path = _visitor_config_path(client_id)
    config_path.write_text(_visitor_config_toml(
        client_id=client_id, alias_octet=alias_octet, secret_key=secret_key,
        server_addr=server_addr, server_port=server_port,
    ))
    _visitors[client_id] = subprocess.Popen(["frpc", "-c", str(config_path)])


def stop_visitor(client_id: str) -> None:
    """Terminate client_id's visitor subprocess and remove its config.

    No-op if no visitor is tracked for this client_id (e.g. it was never
    a relay client) -- cleanup_client_identity calls this unconditionally
    on every unregister.
    """
    proc = _visitors.pop(client_id, None)
    if proc is not None and proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=5)
    _visitor_config_path(client_id).unlink(missing_ok=True)


def frp_status() -> str:
    """"ok" iff the shared frps process (started by start.sh, not this
    module) is reachable on its configured bind port; "not running"
    otherwise.

    frps ships no CLI-friendly "am I up" subcommand comparable to
    `tailscale status`; a raw TCP connect to its own bind port is the
    cheapest reliable signal available from inside this container.
    """
    port = get_config().manual.frps_bind_port
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return "ok"
    except OSError:
        return "not running"
