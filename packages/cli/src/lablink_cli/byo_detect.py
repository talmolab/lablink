"""Auto-detection helpers for `lablink client register` (BYO-box facts).

Each helper has a single, narrow responsibility and returns a value or
None / a benign default — never raises on detection failure. The
`register` command turns "essential field is None" into a user-facing
error; the helpers themselves are pure.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import uuid
from pathlib import Path

_MACHINE_ID_PATHS: list[Path] = [
    Path("/etc/machine-id"),
    Path("/var/lib/dbus/machine-id"),
]


def detect_hostname() -> str | None:
    """Return the box's hostname, or None if empty."""
    name = socket.gethostname()
    return name or None


def detect_lan_ip() -> str | None:
    """Return the IP of the interface that routes to the public internet.

    Uses the UDP-socket trick: connecting a SOCK_DGRAM socket to a public
    address resolves the route locally without sending a packet. The
    socket's local address is the LAN IP that would carry outgoing
    traffic. Returns None on any OSError (no route, no network, etc.).
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def resolve_machine_identity(
    *, fallback_path: Path | None = None
) -> str:
    """Return a stable identifier for this box, creating one if needed.

    Get-or-create, not pure detection: tries /etc/machine-id, then
    /var/lib/dbus/machine-id, and as a last resort **writes** a UUID to
    fallback_path (default ~/.lablink/machine_identity) so the value is
    stable across reboots even on systems without machine-id (e.g.,
    older distributions, custom containers). Callers that only want to
    inspect — without persisting anything — should read the candidate
    paths directly.
    """
    for path in _MACHINE_ID_PATHS:
        try:
            content = path.read_text().strip()
        except OSError:
            continue
        if content:
            return content

    if fallback_path is None:
        fallback_path = Path.home() / ".lablink" / "machine_identity"

    if fallback_path.exists():
        existing = fallback_path.read_text().strip()
        if existing:
            return existing

    value = uuid.uuid4().hex
    fallback_path.parent.mkdir(parents=True, exist_ok=True)
    fallback_path.write_text(value)
    return value


def detect_gpu() -> tuple[bool, str | None]:
    """Return (present, model) by invoking `nvidia-smi -L`.

    Returns (False, None) if nvidia-smi is missing, returns non-zero, or
    its output doesn't parse. Model is extracted from the first line of
    `nvidia-smi -L` (typical format: "GPU 0: NVIDIA T4 (UUID: ...)").
    Never raises.
    """
    if shutil.which("nvidia-smi") is None:
        return (False, None)
    try:
        result = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return (False, None)
    if result.returncode != 0:
        return (False, None)
    first = (result.stdout or "").splitlines()[0:1]
    if not first:
        return (False, None)
    # "GPU 0: NVIDIA T4 (UUID: GPU-xxx)" -> "NVIDIA T4"
    line = first[0]
    after_colon = line.split(":", 1)
    if len(after_colon) != 2:
        return (False, None)
    model = after_colon[1].split("(")[0].strip()
    if not model:
        return (False, None)
    return (True, model)
