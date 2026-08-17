"""Structural test for the X11/ICE socket-dir pre-create in start.sh.

start.sh runs as the non-root `client` user, so Xvnc and libICE cannot
create /tmp/.X11-unix and /tmp/.ICE-unix themselves and X.Org's trans_mkdir
logs `_XSERVTransmkdir: ERROR: euid != 0 ...` / `_IceTransmkdir: ERROR ...`
on every boot. Benign, but the literal word ERROR is the entire errors-only
log view on a healthy VM. Pre-creating the dirs root:root 1777 silences it,
and the create must happen before Xvnc launches or it is pointless.

Same text-assertion approach as test_start_sh_status.py: start.sh is not
sourceable as a whole (it execs stdout through a tagger and backgrounds
Xvnc), so assert against the script text.
"""

from pathlib import Path

import pytest

START_SH = Path(__file__).resolve().parents[1] / "start.sh"


@pytest.fixture(scope="module")
def script_text() -> str:
    return START_SH.read_text()


def _line_of(text: str, needle: str) -> int:
    for i, ln in enumerate(text.splitlines()):
        if needle in ln:
            return i
    raise AssertionError(f"{needle!r} not found in start.sh")


def test_socket_dirs_are_created_root_owned_with_sticky_bit(script_text):
    """Both dirs, made with sudo (non-root user can't otherwise) and chmod
    1777 — the standard /tmp/.X11-unix state trans_mkdir accepts silently."""
    mkdir = _line_of(script_text, "sudo mkdir -p /tmp/.X11-unix /tmp/.ICE-unix")
    chmod = _line_of(script_text, "sudo chmod 1777 /tmp/.X11-unix /tmp/.ICE-unix")
    assert mkdir < chmod


def test_socket_dirs_created_before_xvnc_launches(script_text):
    """A pre-create after Xvnc has already started does nothing — the error
    is emitted during Xvnc's own startup."""
    mkdir = _line_of(script_text, "sudo mkdir -p /tmp/.X11-unix /tmp/.ICE-unix")
    xvnc = _line_of(script_text, "Xvnc :1")
    assert mkdir < xvnc
