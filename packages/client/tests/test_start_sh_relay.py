"""Structural tests for start.sh's relay (frpc proxy) block.

Text assertions rather than execution, for the same reason as
test_start_sh_status.py: start.sh execs stdout through a tagger and
launches long-running services, so it isn't sourceable as a whole.

Each assertion here guards a failure mode that produces NO error
message, which is why they are worth pinning:
  - a missing secret silently yielding no tunnel (design Decision 2)
  - frpc dying on login while the client looks healthy (Decision 4)
  - proxy names not matching the allocator's visitor serverName (Decision 6)
  - the liveness check accidentally testing `sed` instead of frpc
"""

from pathlib import Path

import pytest

START_SH = Path(__file__).resolve().parents[1] / "start.sh"


@pytest.fixture(scope="module")
def script_text() -> str:
    return START_SH.read_text()


@pytest.fixture(scope="module")
def relay_block(script_text) -> str:
    """The `if [ "$CONNECTIVITY" = "relay" ]; then` ... `fi` block."""
    lines = script_text.splitlines()
    start = next(
        i for i, ln in enumerate(lines)
        if ln.startswith('if [ "$CONNECTIVITY" = "relay" ]')
    )
    end = next(i for i, ln in enumerate(lines[start:], start) if ln == "fi")
    return "\n".join(lines[start:end + 1])


def test_relay_block_exists(relay_block):
    assert "frpc" in relay_block


def test_gated_on_connectivity_not_on_secret_presence(script_text):
    """Design Decision 2: gating on FRPS_AUTH_TOKEN's presence would make
    a missing secret a silent no-tunnel. Gate on CONNECTIVITY instead."""
    assert 'if [ "$CONNECTIVITY" = "relay" ]' in script_text
    assert '[ -n "$FRPS_AUTH_TOKEN" ]' not in script_text


def test_requires_all_three_secrets(relay_block):
    for var in ("RELAY_SERVER_ADDR", "RELAY_SECRET_KEY", "FRPS_AUTH_TOKEN"):
        assert var in relay_block


def test_missing_secret_reports_error_status(relay_block):
    """Must fail the way the tailscale path fails, not merely warn."""
    assert "STATUS_SUPERSEDED_FILE" in relay_block
    assert 'send_status "error"' in relay_block
    assert "exit 1" in relay_block


def test_config_written_with_owner_only_permissions(relay_block):
    """frpc.toml holds the STCP secretKey and auth.token."""
    assert "umask 077" in relay_block


def test_config_carries_the_control_plane_auth_token(relay_block):
    """Design Decision 4 / the Plan 1 outage: without auth.token frps
    rejects the login and frpc exits at once."""
    assert "auth.token" in relay_block


def test_proxy_names_match_the_allocator_visitor_servername(relay_block):
    """Design Decision 6: these must equal the visitor's serverName,
    which the allocator derives from the registered hostname ($VM_NAME).
    A mismatch produces no error on either side."""
    assert '"$VM_NAME-kasmvnc"' in relay_block
    assert '"$VM_NAME-agent"' in relay_block


def test_proxies_target_loopback(relay_block):
    assert 'localIP = "127.0.0.1"' in relay_block
    assert "localPort = 6080" in relay_block
    assert "localPort = 7070" in relay_block


def test_liveness_check_uses_process_substitution_not_a_pipeline(relay_block):
    """After a pipeline, `$!` is the PID of the LAST stage -- `sed` --
    which survives whether or not frpc did, so `kill -0` would always
    pass and the whole check would be vacuous. Process substitution keeps
    frpc as the backgrounded command."""
    assert "> >(sed" in relay_block
    assert "| sed -u 's/^/[frpc] /' >&5 &" not in relay_block


def test_verifies_frpc_survived_login(relay_block):
    assert 'kill -0 "$FRPC_PID"' in relay_block


def test_relay_block_precedes_the_custom_startup_script(script_text):
    """frpc must be up before a session can be assigned, and the custom
    startup script can run for minutes."""
    lines = script_text.splitlines()
    relay_at = next(
        i for i, ln in enumerate(lines)
        if ln.startswith('if [ "$CONNECTIVITY" = "relay" ]')
    )
    script_at = next(
        i for i, ln in enumerate(lines) if "custom-startup.sh" in ln
    )
    assert relay_at < script_at
