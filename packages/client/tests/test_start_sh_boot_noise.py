"""Structural tests for start.sh's boot-noise cleanup.

Each guards one fix that keeps a healthy boot's log free of spurious
error/warning output. Same text-assertion approach as
test_start_sh_status.py: start.sh is not sourceable as a whole.
"""

from pathlib import Path

import pytest

START_SH = Path(__file__).resolve().parents[1] / "start.sh"


@pytest.fixture(scope="module")
def script_text() -> str:
    return START_SH.read_text()


def test_custom_startup_script_is_not_chmodded(script_text):
    """The script is only ever invoked via `bash .../custom-startup.sh`, so
    +x is pointless -- and the mount is read-only, so the chmod just logged
    "chmod: ... Read-only file system" on every boot."""
    assert "chmod +x /docker_scripts/custom-startup.sh" not in script_text
    # It must still be *run* via bash (the reason the chmod is unnecessary).
    assert "bash /docker_scripts/custom-startup.sh" in script_text


def test_xstartup_disables_the_at_spi_bridge(script_text):
    """No accessibility bus exists in this container; without NO_AT_BRIDGE=1
    every GTK app the session spawns logs a dbind-WARNING AT-SPI line. The
    export must be written into xstartup (the session's environment), and
    before the exec line -- nothing after an exec runs."""
    lines = script_text.splitlines()
    export = next(
        i for i, ln in enumerate(lines) if "export NO_AT_BRIDGE=1" in ln
    )
    exec_session = next(
        i for i, ln in enumerate(lines) if "exec dbus-launch" in ln
    )
    assert export < exec_session


def test_metrics_curl_is_silent(script_text):
    """Without -sS the vm-metrics POST dumps curl's progress table
    ("% Total  % Received ...") into the boot log."""
    metrics_curl = next(
        ln
        for ln in script_text.splitlines()
        if "curl" in ln and "/api/vm-metrics/" in ln
    )
    assert "-sS" in metrics_curl
