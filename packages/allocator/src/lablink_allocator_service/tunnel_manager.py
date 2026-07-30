"""Reverse-tunnel connectivity's server-side bookkeeping.

One `wstunnel` server runs for the whole deployment (started by start.sh),
and each client attaches to it over a WebSocket carrying its own path
prefix. This module owns the two things the allocator must control:

1. The restrictions file. wstunnel's reverse-tunnel bind address is chosen
   by the CLIENT, so without restrictions any client holding a valid
   client_secret could bind another client's loopback alias and receive
   that client's student sessions. Each rule pins one path prefix to one
   /32 alias and the two ports we tunnel. wstunnel reloads the file
   automatically when it changes, so no restart or signal is needed.

2. Which aliases actually have a client attached. A bound port is NOT
   evidence of an attached client: wstunnel keeps a reverse-tunnel
   listener bound for --remote-to-local-server-idle-timeout after the
   client leaves, and connections to an orphaned listener hang rather than
   being refused (measured: 12s, no response). Health must therefore
   observe the pairing, not the process or the port.

Schema note: verified against the real wstunnel v10.6.2 binary (image tag
"v10.6.2", not "10.6.2" -- ghcr.io only publishes the v-prefixed tag). The
brief's `port: [{start: N, end: N}, ...]` form is rejected with
`invalid type: map, expected a string`; the accepted shape is a list of
port-number strings, each parsed as a single-port range:

    restrictions:
      - name: vm-1
        match:
          - !PathPrefix "tunnel/vm-1-abc123"
        allow:
          - !ReverseTunnel
            port: ["6080", "7070"]
            cidr: ["127.0.0.10/32"]

Confirmed via `--log-lvl DEBUG`, which echoes the parsed rule back as
`port: [6080..=6080, 7070..=7070]`. Re-verify when bumping the pinned
version.
"""
from __future__ import annotations

import hashlib
import os
import socket
from pathlib import Path

TUNNEL_DIR = Path("/tmp/lablink-tunnel")
RESTRICTIONS_PATH = TUNNEL_DIR / "restrictions.yaml"
TUNNEL_PORTS = (6080, 7070)
# Where the tunnel server listens inside the container; nginx proxies to it.
TUNNEL_SERVER_PORT = 8080

# client_id -> (alias_octet, prefix). Module-level, like secret_hash's
# cache: one allocator process per deployment.
_restrictions: dict[str, tuple[int, str]] = {}


def path_prefix(client_id: str, secret: str) -> str:
    """Per-client URL segment: `<client_id>-<digest>`.

    Derived from the client's own secret so it is stable across restarts
    and needs no storage of its own. It identifies the client to
    /internal/tunnel_auth; the bearer token is what authenticates.
    """
    digest = hashlib.sha256(f"{client_id}:{secret}".encode()).hexdigest()[:16]
    return f"{client_id}-{digest}"


def _render() -> str:
    lines = ["restrictions:"]
    for client_id, (octet, prefix) in sorted(_restrictions.items()):
        ports = ", ".join(f'"{p}"' for p in TUNNEL_PORTS)
        lines += [
            f"  - name: {client_id}",
            "    match:",
            f'      - !PathPrefix "tunnel/{prefix}"',
            "    allow:",
            "      - !ReverseTunnel",
            f"        port: [{ports}]",
            f'        cidr: ["127.0.0.{octet}/32"]',
        ]
    return "\n".join(lines) + "\n"


def _write() -> None:
    TUNNEL_DIR.mkdir(parents=True, exist_ok=True)
    TUNNEL_DIR.chmod(0o700)
    # Create at 0600 up front rather than write-then-chmod: the file names
    # each client's path prefix, which is derived from its secret.
    fd = os.open(RESTRICTIONS_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(_render())
    os.chmod(RESTRICTIONS_PATH, 0o600)


def authorize_client(*, client_id: str, alias_octet: int, prefix: str) -> None:
    """Permit exactly this client to bind exactly its own alias."""
    _restrictions[client_id] = (alias_octet, prefix)
    _write()


def revoke_client(client_id: str) -> None:
    """Drop this client's permission. No-op if it was never a tunnel client."""
    if _restrictions.pop(client_id, None) is None:
        return
    _write()


def _proc_net_tcp() -> str:
    try:
        return Path("/proc/net/tcp").read_text()
    except OSError:
        return ""


def attached_aliases() -> set[int]:
    """Alias octets with a listening reverse-tunnel socket right now.

    Parses /proc/net/tcp because there is no wstunnel API for it. State
    "0A" is TCP_LISTEN; local_address is `<hex ip>:<hex port>` with the IP
    in network-reversed byte order, so 127.0.0.10 is 0A00007F.
    """
    found: set[int] = set()
    for line in _proc_net_tcp().splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4 or parts[3] != "0A":
            continue
        hex_ip, _, hex_port = parts[1].partition(":")
        if len(hex_ip) != 8 or not hex_ip.upper().endswith("00007F"):
            continue
        if int(hex_port, 16) not in TUNNEL_PORTS:
            continue
        found.add(int(hex_ip[:2], 16))
    return found


def tunnel_status() -> str:
    """"ok" iff the shared tunnel server is accepting connections."""
    try:
        with socket.create_connection(("127.0.0.1", TUNNEL_SERVER_PORT), timeout=2):
            return "ok"
    except OSError:
        return "not running"
