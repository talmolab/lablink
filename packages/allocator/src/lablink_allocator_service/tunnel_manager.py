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
          - !PathPrefix "tun-vm-1-abc123"
        allow:
          - !ReverseTunnel
            port: ["6080", "7070"]
            cidr: ["127.0.0.10/32"]

Confirmed via `--log-lvl DEBUG`, which echoes the parsed rule back as
`port: [6080..=6080, 7070..=7070]`. Re-verify when bumping the pinned
version.

`!PathPrefix` matches ONLY the client's first path segment (also verified
against 10.6.2): a match value of `tunnel/<prefix>` can never fire against
a client dialing in on `-P tunnel/<prefix>`, because wstunnel only ever
compares that first segment to the match string. The only way this rule
can both match AND stay per-client is for the match value to BE the whole
first segment -- so the prefix itself must be dialed as the first segment
(no shared "tunnel/" root), which is why `path_prefix()` below returns
`tun-<client_id>-<digest>` rather than something nested under a shared
prefix. Confirmed end to end: a client presenting its own prefix as the
first path segment was accepted onto its own alias; the same client
presenting another client's alias in `-R` was refused with "Rejecting
connection with not allowed destination".

Security note: `client_id` is the DB `hostname`, which reaches this module
from client-controlled registration input -- it is NOT validated upstream
beyond truthiness. Every function that renders it into the restrictions
file therefore validates it here (see `_is_safe_client_id`) rather than
trusting the caller, and rendering itself goes through `yaml.safe_dump`
(not f-string/string-building) so a value that somehow slipped past
validation still can't forge YAML structure. Both are load-bearing: the
charset check is what stops a multi-line hostname from ever reaching the
renderer, and safe_dump is what stops any single-line-but-still-special
YAML character (quotes, colons, `#`, etc.) from doing so.
"""
from __future__ import annotations

import hashlib
import os
import re
import socket
from pathlib import Path

import yaml

TUNNEL_DIR = Path("/tmp/lablink-tunnel")
RESTRICTIONS_PATH = TUNNEL_DIR / "restrictions.yaml"
TUNNEL_PORTS = (6080, 7070)
# Where the tunnel server listens inside the container; nginx proxies to it.
TUNNEL_SERVER_PORT = 8080

# client_id is the DB hostname: registration only checks it's truthy (see
# routes/registration.py), so this module can't trust it arrived sane.
# Reject anything outside a conservative charset rather than trying to
# escape it -- it ends up as a YAML mapping key/value AND a path segment
# (via path_prefix), so "sanitize" would need to satisfy both consumers.
_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,252}$")
# path_prefix() = "tun-<client_id>-<digest>" (digest is 16 hex chars), so
# the same charset applies with a little headroom for that prefix/suffix.
_PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,299}$")

# A rendered restriction is one octet in a 127.0.0.0/8 /32 CIDR. 0 and 255
# are excluded as the conventional network/broadcast-shaped ends of a
# /24-sized block, even though loopback doesn't strictly enforce that.
_MIN_ALIAS_OCTET = 1
_MAX_ALIAS_OCTET = 254


def _is_safe_client_id(client_id: str) -> bool:
    # fullmatch, not match: `match` + a `$`-anchored pattern still accepts
    # a single trailing newline ("vm-1\n"), since Python's `$` matches just
    # before a trailing newline as well as end-of-string. safe_dump blocks
    # the actual YAML-injection exploit either way, but this boundary
    # check is what the module docstring claims stops a trailing newline
    # at all, so it must actually do that.
    return bool(_CLIENT_ID_RE.fullmatch(client_id))


def _is_safe_prefix(prefix: str) -> bool:
    return bool(_PREFIX_RE.fullmatch(prefix))


def is_valid_alias_octet(octet: int) -> bool:
    """True iff *octet* is in the range a /32 loopback rule can express.

    Exposed so callers (routes/registration.py) can reject an
    out-of-range allocation with a clean error response before writing a
    client row, instead of finding out only when authorize_client raises.
    """
    return _MIN_ALIAS_OCTET <= octet <= _MAX_ALIAS_OCTET


# client_id -> (alias_octet, prefix). Module-level, like secret_hash's
# cache: one allocator process per deployment.
_restrictions: dict[str, tuple[int, str]] = {}
# True once this process has attempted to load _restrictions from disk.
# `restart: unless-stopped` leaves the restrictions file (and the DB) in
# place across a crash/restart -- only a container *recreate* wipes both
# together, so the two stay consistent. Without this, _write() renders the
# WHOLE file from this in-memory dict, so the first authorize_client() call
# after a bare restart would silently drop every previously-authorized
# client's rule.
_hydrated = False


class _PathPrefix(str):
    """Marker type so the dumper below emits `!PathPrefix "value"`."""


class _ReverseTunnelRule(dict):
    """Marker type so the dumper below emits `!ReverseTunnel {...}`."""


def _represent_path_prefix(dumper: yaml.Dumper, data: "_PathPrefix"):
    return dumper.represent_scalar("!PathPrefix", str(data))


def _represent_reverse_tunnel(dumper: yaml.Dumper, data: "_ReverseTunnelRule"):
    return dumper.represent_mapping("!ReverseTunnel", dict(data))


yaml.SafeDumper.add_representer(_PathPrefix, _represent_path_prefix)
yaml.SafeDumper.add_representer(_ReverseTunnelRule, _represent_reverse_tunnel)

# So _render()'s self-check (below) can round-trip its own output: SafeLoader
# has no constructor for our custom tags by default and would otherwise
# raise before the check ever ran.
yaml.SafeLoader.add_constructor(
    "!PathPrefix", lambda loader, node: loader.construct_scalar(node)
)
yaml.SafeLoader.add_constructor(
    "!ReverseTunnel", lambda loader, node: loader.construct_mapping(node)
)


def path_prefix(client_id: str, secret: str) -> str:
    """Per-client value the client must dial as its first path segment.

    `tun-<client_id>-<digest>`. Must BE the first path segment, not a
    sub-path under some shared root: wstunnel's `!PathPrefix` restriction
    matcher only inspects the first segment (see the module docstring), so
    a value like "tunnel/<this>" could never match. The `tun-` marker is
    what lets nginx tell a tunnel attach apart from an application route
    now that the prefix sits at the URL root instead of under a fixed
    "tunnel/" segment.

    Derived from the client's own secret so it is stable across restarts
    and needs no storage of its own. It identifies the client to
    /internal/tunnel_auth; the bearer token is what authenticates.
    """
    digest = hashlib.sha256(f"{client_id}:{secret}".encode()).hexdigest()[:16]
    return f"tun-{client_id}-{digest}"


def _render() -> str:
    doc = {
        "restrictions": [
            {
                "name": client_id,
                # !PathPrefix matches only the first path segment (measured
                # against 10.6.2), so the match value must BE the prefix,
                # not "tunnel/<prefix>" -- the latter can never fire.
                "match": [_PathPrefix(prefix)],
                "allow": [
                    _ReverseTunnelRule(
                        {
                            "port": [str(p) for p in TUNNEL_PORTS],
                            "cidr": [f"127.0.0.{octet}/32"],
                        }
                    )
                ],
            }
            for client_id, (octet, prefix) in sorted(_restrictions.items())
        ]
    }
    text = yaml.safe_dump(doc, default_flow_style=False, sort_keys=False)
    # Belt and braces: authorize_client already rejects an unsafe client_id
    # before it ever reaches here, and safe_dump can't be tricked into
    # emitting extra YAML structure from a string value. This re-parses the
    # output and checks the entry count so a future regression (e.g. someone
    # reverting to f-string rendering) fails loudly here instead of quietly
    # widening a client's access.
    assert len(yaml.safe_load(text)["restrictions"]) == len(_restrictions)
    return text


def _write() -> None:
    TUNNEL_DIR.mkdir(parents=True, exist_ok=True)
    TUNNEL_DIR.chmod(0o700)
    # Create at 0600 up front rather than write-then-chmod: the file names
    # each client's path prefix, which is derived from its secret.
    fd = os.open(RESTRICTIONS_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(_render())
    os.chmod(RESTRICTIONS_PATH, 0o600)


def _hydrate_from_disk() -> None:
    """Load _restrictions from the on-disk file, once per process.

    Runs before the first authorize_client()/revoke_client() mutation so a
    freshly-restarted process doesn't treat "empty in-memory dict" as
    "no clients have tunnels" -- see _hydrated's comment. Best-effort: a
    missing or malformed file just means "nothing to load" rather than a
    failure at import time or on the first registration after a restart.
    """
    global _hydrated
    if _hydrated:
        return
    _hydrated = True  # only ever try once, even if this fails
    try:
        text = RESTRICTIONS_PATH.read_text()
    except OSError:
        return
    try:
        doc = yaml.safe_load(text) or {}
        loaded: dict[str, tuple[int, str]] = {}
        for entry in doc.get("restrictions") or []:
            name = entry["name"]
            prefix = str(entry["match"][0])
            cidr = entry["allow"][0]["cidr"][0]
            octet = int(cidr.rsplit(".", 1)[-1].split("/")[0])
            loaded[name] = (octet, prefix)
    except (yaml.YAMLError, KeyError, IndexError, TypeError, ValueError):
        # Malformed file: fall back to empty rather than raising, and
        # rather than trusting a partially-parsed (possibly corrupt) set.
        return
    _restrictions.update(loaded)


def authorize_client(*, client_id: str, alias_octet: int, prefix: str) -> None:
    """Permit exactly this client to bind exactly its own alias.

    Raises ValueError -- before any file work -- if client_id/prefix carry
    characters this module can't safely render, or if alias_octet is
    outside the range a /32 loopback rule can express. This is the trust
    boundary: client_id is attacker-controlled (see the module docstring),
    so it's validated here rather than assumed clean by callers.
    """
    _hydrate_from_disk()
    if not _is_safe_client_id(client_id):
        raise ValueError(f"unsafe client_id for tunnel restrictions: {client_id!r}")
    if not _is_safe_prefix(prefix):
        raise ValueError(f"unsafe prefix for tunnel restrictions: {prefix!r}")
    if not is_valid_alias_octet(alias_octet):
        raise ValueError(
            f"alias_octet {alias_octet!r} out of range "
            f"[{_MIN_ALIAS_OCTET}, {_MAX_ALIAS_OCTET}]"
        )
    _restrictions[client_id] = (alias_octet, prefix)
    _write()


def revoke_client(client_id: str) -> None:
    """Drop this client's permission. No-op if it was never a tunnel client.

    No client_id validation here: an unsafe id can never have made it into
    _restrictions in the first place (authorize_client rejects it before
    writing), so the plain dict.pop miss already gives the right no-op
    behavior. This also has to stay a no-op, not raise -- it runs on every
    client unregister.
    """
    _hydrate_from_disk()
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
