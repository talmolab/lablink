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

import json
import os
import re
import socket
import subprocess
from pathlib import Path

from lablink_allocator_service.get_config import get_config

VISITOR_CONFIG_DIR = Path("/tmp/lablink-frp-visitors")

# client_id is a caller-supplied hostname that reaches BOTH a filesystem
# path and the body of a config file, so it is constrained to a hostname-ish
# charset here rather than trusted. Without this, "../../etc/foo" escapes
# VISITOR_CONFIG_DIR (arbitrary write via start_visitor, arbitrary unlink
# via stop_visitor) and a quote or newline breaks out of a TOML string.
# routes/registration.py validates the same shape at the API boundary; this
# is the defense-in-depth copy so the module is safe on its own.
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$")


def _is_safe_client_id(client_id: str) -> bool:
    return bool(_CLIENT_ID_RE.fullmatch(client_id or ""))


def _toml_str(value: str) -> str:
    """Encode *value* as an escaped TOML basic string.

    TOML basic strings share JSON's escape rules, so json.dumps is a
    correct encoder and keeps a stray quote in operator-supplied config
    (e.g. server_addr) from terminating the string and corrupting the
    file."""
    return json.dumps(value)

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
    server_addr: str, server_port: int, auth_token: str,
) -> str:
    alias = f"127.0.0.{alias_octet}"
    return (
        f"serverAddr = {_toml_str(server_addr)}\n"
        f"serverPort = {int(server_port)}\n"
        # The allocator's own visitor is an frpc client too, so it must
        # present the deployment's control-plane token exactly like a relay
        # client's proxy-side frpc does. Without it frps rejects the login
        # ("token in login doesn't match token from configuration") and
        # frpc exits immediately -- with loginFailExit on by default it
        # does not even retry -- so every relay client is unreachable while
        # registration still returns a healthy 200.
        f"auth.token = {_toml_str(auth_token)}\n"
        "\n"
        "[[visitors]]\n"
        f"name = {_toml_str(f'{client_id}-kasmvnc-visitor')}\n"
        'type = "stcp"\n'
        f"serverName = {_toml_str(f'{client_id}-kasmvnc')}\n"
        f"secretKey = {_toml_str(secret_key)}\n"
        f"bindAddr = {_toml_str(alias)}\n"
        "bindPort = 6080\n"
        "\n"
        "[[visitors]]\n"
        f"name = {_toml_str(f'{client_id}-agent-visitor')}\n"
        'type = "stcp"\n'
        f"serverName = {_toml_str(f'{client_id}-agent')}\n"
        f"secretKey = {_toml_str(secret_key)}\n"
        f"bindAddr = {_toml_str(alias)}\n"
        "bindPort = 7070\n"
    )


def start_visitor(
    *, client_id: str, alias_octet: int, secret_key: str,
    server_addr: str, server_port: int, auth_token: str,
) -> None:
    """Spawn this client's dedicated frpc-visitor subprocess.

    Idempotent for a *live* visitor: an already-running visitor for this
    client_id is left alone (re-registration is expected to reuse the same
    alias/secret rather than churn the subprocess). A tracked-but-dead
    visitor is replaced.

    Raises ValueError for a client_id outside the hostname charset, before
    any filesystem or subprocess work happens.
    """
    if not _is_safe_client_id(client_id):
        raise ValueError(
            f"unsafe client_id for a relay visitor config: {client_id!r}"
        )
    running = _visitors.get(client_id)
    if running is not None and running.poll() is None:
        return
    VISITOR_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # mkdir(mode=) is masked by umask and is a no-op when the directory
    # already exists, so set the mode explicitly.
    VISITOR_CONFIG_DIR.chmod(0o700)
    config_path = _visitor_config_path(client_id)
    # Create at 0600 up front rather than write-then-chmod, so the embedded
    # per-client secretKey is never even briefly world-readable. The
    # explicit chmod covers a pre-existing file, whose mode os.open leaves
    # untouched.
    fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(_visitor_config_toml(
            client_id=client_id, alias_octet=alias_octet,
            secret_key=secret_key, server_addr=server_addr,
            server_port=server_port, auth_token=auth_token,
        ))
    os.chmod(config_path, 0o600)
    _visitors[client_id] = subprocess.Popen(["frpc", "-c", str(config_path)])


def stop_visitor(client_id: str) -> None:
    """Terminate client_id's visitor subprocess and remove its config.

    No-op if no visitor is tracked for this client_id (e.g. it was never
    a relay client) -- cleanup_client_identity calls this unconditionally
    on every unregister.

    An unsafe client_id is a silent no-op rather than a raise: this runs on
    every unregister, so raising would turn a harmless request into a 500,
    and start_visitor's own check means nothing can ever have been created
    under such an id. Critically, it returns *before* deriving a path, so a
    traversal id can never reach unlink().
    """
    if not _is_safe_client_id(client_id):
        return
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
