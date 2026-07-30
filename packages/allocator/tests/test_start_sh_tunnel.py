"""Structural tests for start.sh's tunnel block — text assertions rather
than execution, for the same reason as test_start_sh_status.py: start.sh
launches long-running services and isn't sourceable."""
from pathlib import Path

import pytest

START_SH = Path(__file__).resolve().parents[1] / "start.sh"


@pytest.fixture(scope="module")
def script_text() -> str:
    return START_SH.read_text()


@pytest.fixture(scope="module")
def block() -> str:
    lines = START_SH.read_text().splitlines()
    start = next(
        i for i, ln in enumerate(lines)
        if ln.startswith('if [ "$CONNECTIVITY_MODE" = "reverse_tunnel" ]')
    )
    end = next(i for i, ln in enumerate(lines[start:], start) if ln == "fi")
    return "\n".join(lines[start:end + 1])


def test_gated_on_connectivity_mode(block):
    assert 'if [ "$CONNECTIVITY_MODE" = "reverse_tunnel" ]' in block


def test_mode_is_read_from_the_mounted_config_not_an_env_var(script_text):
    """Nothing sets CONNECTIVITY_MODE in the container environment, and
    nothing should: this mode adds no env and no port to the compose stack
    (Task 14 pins that). The config file the allocator already mounts is the
    only source of truth."""
    assert "CONNECTIVITY_MODE=$(" in script_text
    assert "/config/config.yaml" in script_text


def test_binds_loopback_only(block):
    """The tunnel server must never be reachable except through nginx."""
    assert "ws://127.0.0.1:8080" in block
    assert "0.0.0.0" not in block


def test_idle_timeout_is_short(block):
    """Default is 3 minutes, during which an orphaned listener accepts
    connections and hangs. Anything above ~30s reintroduces that window."""
    import re

    m = re.search(r"--remote-to-local-server-idle-timeout\s+(\d+)s", block)
    assert m, "idle timeout not set"
    assert int(m.group(1)) <= 30


def test_uses_the_restrictions_file(block):
    assert "--restrict-config /tmp/lablink-tunnel/restrictions.yaml" in block


def test_restrictions_file_exists_before_the_server_starts(block):
    """wstunnel refuses to start if --restrict-config points at a missing
    file, and the first client registers only after Flask is up."""
    assert "restrictions:" in block  # seeds an empty document
