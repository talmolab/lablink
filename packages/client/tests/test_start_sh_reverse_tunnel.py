"""Structural tests for start.sh's reverse-tunnel block. Text assertions
rather than execution (start.sh launches long-running services). Each one
guards a failure mode that produces no error message on its own."""
from pathlib import Path

import pytest

START_SH = Path(__file__).resolve().parents[1] / "start.sh"


@pytest.fixture(scope="module")
def block() -> str:
    lines = START_SH.read_text().splitlines()
    start = next(
        i for i, ln in enumerate(lines)
        if ln.startswith('if [ "$CONNECTIVITY" = "reverse_tunnel" ]')
    )
    end = next(i for i, ln in enumerate(lines[start:], start) if ln == "fi")
    return "\n".join(lines[start:end + 1])


def test_gated_on_connectivity_not_on_secret_presence(block):
    """Gating on a secret's presence would make a missing value a silent
    no-tunnel; the allocator already told us the mode."""
    assert 'if [ "$CONNECTIVITY" = "reverse_tunnel" ]' in block


def test_requires_its_inputs(block):
    required = "for v in TUNNEL_URL TUNNEL_PATH_PREFIX TUNNEL_BIND_ADDR CLIENT_SECRET"
    assert required in block


def test_passes_the_path_prefix_explicitly(block):
    """Without -P the client ignores the URL path and requests /v1/events,
    which matches no tunnel location — measured against the real client."""
    assert '-P "$TUNNEL_PATH_PREFIX"' in block


def test_missing_input_reports_error_status(block):
    assert "STATUS_SUPERSEDED_FILE" in block
    assert 'send_status "error"' in block
    assert "exit 1" in block


def test_binds_the_allocator_assigned_alias_for_both_ports(block):
    assert '-R tcp://$TUNNEL_BIND_ADDR:6080:127.0.0.1:6080' in block
    assert '-R tcp://$TUNNEL_BIND_ADDR:7070:127.0.0.1:7070' in block


def test_authenticates_with_the_client_secret(block):
    assert 'Authorization: Bearer $CLIENT_SECRET' in block


def test_verifies_the_tunnel_survived_attaching(block):
    """wstunnel retries a rejected upgrade forever, so a wrong secret would
    otherwise leave the client reporting healthy while unreachable."""
    assert 'kill -0 "$TUNNEL_PID"' in block


def test_detects_a_rejected_upgrade_not_just_a_dead_process(block):
    """The load-bearing check. wstunnel does NOT exit on a rejected
    handshake -- it logs `Invalid status code: 401` and retries forever, so
    a process-liveness check alone reports healthy while the client is
    unreachable. That is precisely the failure class this feature has
    shipped three times. Scan the tunnel's own output for a failed
    handshake during the wait window."""
    assert "Invalid status code" in block or "handshake" in block
    assert "TUNNEL_LOG" in block


def test_liveness_check_uses_process_substitution_not_a_pipeline(block):
    """After a pipeline, $! is the PID of the LAST stage (sed), which
    survives whether or not the tunnel did -- making the check vacuous."""
    assert "> >(sed" in block


def test_precedes_the_custom_startup_script(block):
    text = START_SH.read_text().splitlines()
    tunnel_at = next(
        i for i, ln in enumerate(text)
        if ln.startswith('if [ "$CONNECTIVITY" = "reverse_tunnel" ]')
    )
    script_at = next(i for i, ln in enumerate(text) if "custom-startup.sh" in ln)
    assert tunnel_at < script_at
