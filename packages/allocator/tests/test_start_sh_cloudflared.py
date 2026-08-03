"""Structural tests for start.sh's Cloudflare Tunnel connector block.

start.sh launches long-running services and `exec`s nginx, so it isn't
sourceable — these assert against the script text rather than executing it,
the same approach as the client package's test_start_sh_status.py. The
connector's runtime behaviour is verified by hand against a real tunnel.
"""

from pathlib import Path

import pytest

START_SH = Path(__file__).resolve().parents[1] / "start.sh"


@pytest.fixture(scope="module")
def script_text() -> str:
    return START_SH.read_text()


@pytest.fixture(scope="module")
def block(script_text: str) -> str:
    lines = script_text.splitlines()
    start = next(
        i
        for i, ln in enumerate(lines)
        if ln.startswith('if [ "$PARTICIPANT_EXPOSURE" = "cloudflare_tunnel" ]')
    )
    end = next(i for i in range(start, len(lines)) if lines[i] == "fi")
    return "\n".join(lines[start : end + 1])


def test_gated_on_the_exposure_mode(block):
    """lan_direct/funnel deployments must never start a connector."""
    assert 'if [ "$PARTICIPANT_EXPOSURE" = "cloudflare_tunnel" ]' in block


def test_empty_token_exits_nonzero(block):
    """A mode set with no token must fail loudly. Silently skipping the
    connector produces an allocator that looks healthy and is unreachable
    — the exact failure class that shipped three times in this subsystem."""
    assert '-z "$CLOUDFLARE_TUNNEL_TOKEN"' in block
    assert "exit 1" in block


def test_targets_the_containers_own_nginx_port(block):
    """The connector reaches nginx on :5000 inside this container. It is
    NOT told the origin here — the ingress config lives in Cloudflare —
    but the port must appear in a comment so the docs' instruction to type
    http://localhost:5000 stays traceable to the code."""
    assert "5000" in block


def test_runs_with_the_token_and_no_autoupdate(block):
    assert "--token" in block
    assert '"$CLOUDFLARE_TUNNEL_TOKEN"' in block
    # The version is pinned in the Dockerfile; letting the binary update
    # itself at runtime would silently un-pin it.
    assert "--no-autoupdate" in block


def test_token_is_dropped_from_the_environment_before_launching(block):
    """cloudflared logs its entire environment at INFO on startup, so an
    exported token lands in `docker logs` verbatim — persisted and readable
    by anyone with docker access. It must be copied to a local variable and
    unset before the connector starts."""
    lines = block.splitlines()
    unset = next(
        i for i, ln in enumerate(lines) if "unset CLOUDFLARE_TUNNEL_TOKEN" in ln
    )
    launch = next(
        i for i, ln in enumerate(lines) if "cloudflared" in ln and "--token" in ln
    )
    assert unset < launch, "the unset must precede the connector launch"
    # ...and the launch must not reach for the exported name again.
    assert "$CLOUDFLARE_TUNNEL_TOKEN" not in lines[launch]


def test_backgrounded_so_nginx_still_execs(block):
    assert block.rstrip().endswith("fi")
    assert "&" in block


def test_connector_block_precedes_the_nginx_exec(script_text):
    lines = script_text.splitlines()
    connector = next(
        i for i, ln in enumerate(lines) if "cloudflared" in ln and "--token" in ln
    )
    nginx = next(i for i, ln in enumerate(lines) if ln.startswith("exec nginx"))
    assert connector < nginx, "exec nginx replaces the shell; nothing after it runs"


def test_version_is_pinned_in_both_dockerfiles():
    """A floating tag would change what ships without a code change, and
    the two files must not drift apart."""
    root = START_SH.parent
    if not (root / "Dockerfile").is_file():
        # These tests also run inside the built allocator image, which copies
        # start.sh but not the Dockerfiles. The drift guard's purpose is
        # PR-review time on a full checkout; skip elsewhere.
        pytest.skip(f"Dockerfile not found in {root} (not running from repo tree)")
    for name in ("Dockerfile", "Dockerfile.dev"):
        text = (root / name).read_text()
        assert "ARG CLOUDFLARED_VERSION=2026.7.3" in text, name
        assert "cloudflared-linux-amd64" in text, name
        assert "cloudflared:latest" not in text, name
