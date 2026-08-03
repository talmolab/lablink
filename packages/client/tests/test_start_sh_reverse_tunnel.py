"""Structural tests for start.sh's reverse-tunnel block. Text assertions
rather than execution (start.sh launches long-running services). Each one
guards a failure mode that produces no error message on its own.

The detection logic (grace window that distinguishes a transient non-101
upgrade response from a permanent one) is behavioral, not just structural,
so it is also exercised for real: `_run_detection_logic` extracts that
logic verbatim from start.sh and runs it in a bash subprocess against a
fixture log and a stubbed background process, with the real sleeps shortened
so the test stays fast."""
import re
import subprocess
import tempfile
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


def test_requires_its_inputs_and_aborts_when_one_is_missing(block):
    """Scoped to the validation loop's own lines, not the whole block:
    tunnel_fail and tunnel_check_fatal also contain send_status/exit, so a
    block-wide `in` check would pass even if this loop stopped aborting."""
    loop = next(ln for ln in block.splitlines() if "for v in TUNNEL_URL" in ln)
    assert "TUNNEL_URL TUNNEL_PATH_PREFIX TUNNEL_BIND_ADDR CLIENT_SECRET" in loop
    assert "tunnel_abort" in block
    assert 'send_status "error"' in block
    assert "exit 1" in block


def test_passes_the_path_prefix_explicitly(block):
    """Without -P the client ignores the URL path and requests /v1/events,
    which matches no tunnel location — measured against the real client."""
    assert '-P "$TUNNEL_PATH_PREFIX"' in block


def test_binds_the_allocator_assigned_alias_for_both_ports(block):
    assert '-R tcp://$TUNNEL_BIND_ADDR:6080:127.0.0.1:6080' in block
    assert '-R tcp://$TUNNEL_BIND_ADDR:7070:127.0.0.1:7070' in block


def test_authenticates_with_the_client_secret(block):
    assert 'Authorization: Bearer $CLIENT_SECRET' in block


def test_verifies_the_tunnel_survived_attaching(block):
    """The dead-process branch has no behavioral test (the bash harnesses
    below stand in a live PID), so this text check is its only guard.
    Rejected-upgrade detection IS covered behaviorally — see
    TestDetectionLogicBehavior."""
    assert 'kill -0 "$TUNNEL_PID"' in block


def test_liveness_check_uses_process_substitution_not_a_pipeline(block):
    """After a pipeline, $! is the PID of the LAST stage (sed), which
    survives whether or not the tunnel did -- making the check vacuous."""
    assert "> >(sed" in block


def test_log_is_truncated_before_reuse():
    """docker restart re-runs this script against the SAME filesystem (see
    the STATUS_SUPERSEDED_FILE comment above this block for the identical
    hazard). TUNNEL_LOG is opened with `tee -a`, so a rejected-handshake
    line logged on ANY earlier boot must not survive to poison detection
    on a later, healthy boot. Extracts just the lines between the
    TUNNEL_LOG assignment and the wstunnel launch (truncation must happen
    before the tee starts appending), substitutes a tmp path for the
    hardcoded one, pre-seeds stale content, and confirms it's gone."""
    lines = START_SH.read_text().splitlines()
    start = next(
        i for i, ln in enumerate(lines) if ln.strip().startswith("TUNNEL_LOG=")
    )
    end = next(i for i in range(start, len(lines)) if "wstunnel client" in lines[i])
    snippet = "\n".join(lines[start:end])
    assert ': > "$TUNNEL_LOG"' in snippet, (
        "expected TUNNEL_LOG to be truncated before wstunnel launch"
    )

    with tempfile.TemporaryDirectory() as d:
        log_path = Path(d) / "lablink-tunnel-client.log"
        log_path.write_text("[tunnel] Invalid status code: 401\n")
        harness = snippet.replace("/tmp/lablink-tunnel-client.log", str(log_path))

        result = subprocess.run(
            ["bash", "-c", harness], capture_output=True, text=True, timeout=5,
        )

        assert result.returncode == 0, result.stderr
        assert log_path.read_text() == ""


def test_precedes_the_custom_startup_script(block):
    text = START_SH.read_text().splitlines()
    tunnel_at = next(
        i for i, ln in enumerate(text)
        if ln.startswith('if [ "$CONNECTIVITY" = "reverse_tunnel" ]')
    )
    script_at = next(i for i, ln in enumerate(text) if "custom-startup.sh" in ln)
    assert tunnel_at < script_at


class TestDetectionLogicBehavior:
    """Runs the actual post-launch detection logic from start.sh (from
    `tunnel_fail() {` through the final `echo "Tunnel process running"`) in
    a real bash subprocess, against a fixture TUNNEL_LOG and a stand-in
    background process -- not just asserting the text exists, but that it
    produces the right exit behavior. `sleep 5`/`sleep 3` are shortened so
    each run takes a fraction of a second instead of ~8s."""

    @staticmethod
    def _extract_detection_snippet(script_text: str) -> str:
        start = script_text.index("  tunnel_fail() {")
        end = script_text.index('echo "Tunnel process running')
        snippet = script_text[start:end]
        # Same logic, faster clock -- durations aren't what's under test.
        snippet = re.sub(r"sleep 5\b", "sleep 0.2", snippet)
        snippet = re.sub(r"sleep 3\b", "sleep 0.2", snippet)
        return snippet

    def _run(
        self, log_lines, append_after: str | None = None
    ) -> subprocess.CompletedProcess:
        snippet = self._extract_detection_snippet(START_SH.read_text())
        with tempfile.TemporaryDirectory() as d:
            log_path = Path(d) / "tunnel.log"
            log_path.write_text("\n".join(log_lines) + "\n")
            superseded = Path(d) / "superseded"

            # A real background process this harness controls stands in for
            # wstunnel, so `kill -0 "$TUNNEL_PID"` behaves like it would for
            # a genuinely-alive tunnel. `send_status` is stubbed to report
            # what it was called with instead of hitting the network.
            append_cmd = (
                f'(sleep 0.25; echo "{append_after}" >> "{log_path}") '
                f"</dev/null >/dev/null 2>&1 &\n"
                if append_after else ""
            )
            harness = f"""
set -u
TUNNEL_LOG="{log_path}"
STATUS_SUPERSEDED_FILE="{superseded}"
TUNNEL_URL="wss://allocator.example.com"
TUNNEL_PATH_PREFIX="tun-vm-1-abc"
TUNNEL_BIND_ADDR="127.0.0.10"
CLIENT_SECRET="cs"
send_status() {{ echo "STATUS_CALLED:$1"; return 0; }}
# Defined above the extracted snippet in start.sh, so stand it in here.
tunnel_abort() {{
  echo "$1" >&2
  touch "$STATUS_SUPERSEDED_FILE"
  send_status "error"
  exit 1
}}
# Redirected so this stand-in process doesn't hold the harness's own
# stdout pipe open after the harness itself exits.
sleep 100 </dev/null >/dev/null 2>&1 &
TUNNEL_PID=$!
{append_cmd}{snippet}
echo "REACHED_END"
"""
            return subprocess.run(
                ["bash", "-c", harness], capture_output=True, text=True, timeout=10
            )

    def test_transient_failure_that_recovers_does_not_strand_the_tunnel(self):
        """A 503 logged once (allocator proxy still warming up) followed by
        a successful connect must NOT be treated as fatal."""
        result = self._run([
            "[tunnel] Connecting to wss://allocator.example.com/prefix/",
            "[tunnel] Invalid status code: 503",
            "[tunnel] Connected, tunnel established",
        ])
        assert "STATUS_CALLED:error" not in result.stdout, result.stdout
        assert "REACHED_END" in result.stdout, result.stdout

    def test_persistent_401_fails_fast_without_waiting_out_the_grace_window(self):
        """A wrong secret must still fail fast -- this is the property the
        fix must not trade away."""
        result = self._run([
            "[tunnel] Connecting to wss://allocator.example.com/prefix/",
            "[tunnel] Invalid status code: 401",
        ])
        assert "STATUS_CALLED:error" in result.stdout, result.stdout
        assert "REACHED_END" not in result.stdout, result.stdout

    def test_persistent_non_auth_failure_still_fails_after_the_grace_window(self):
        """A repeated (but not 401/403) failure that is STILL happening when
        the grace window ends must not be waved through just because no
        single grep caught it -- the log keeps growing across the window."""
        result = self._run(
            ["[tunnel] Connecting to wss://allocator.example.com/prefix/",
             "[tunnel] Invalid status code: 503"],
            append_after="[tunnel] Invalid status code: 503",
        )
        assert "STATUS_CALLED:error" in result.stdout, result.stdout
        assert "REACHED_END" not in result.stdout, result.stdout


class TestReachabilityPreflight:
    """Runs the real preflight (from `tunnel_abort() {` through the line that
    announces the tunnel) in a bash subprocess with `curl` stubbed, so the
    probe's decision is what is under test rather than whether an allocator
    happens to be listening on this machine."""

    @staticmethod
    def _extract_preflight(script_text: str) -> str:
        start = script_text.index("  tunnel_abort() {")
        end = script_text.index('  echo "Opening tunnel to')
        return re.sub(r"sleep 3\b", "sleep 0.05", script_text[start:end])

    def _run(
        self, curl_rc: int = 0, curl_body: str | None = None
    ) -> subprocess.CompletedProcess:
        """curl_body overrides the stub for tests that need the probe's
        *flags* to decide the outcome rather than a fixed exit code."""
        stub = curl_body if curl_body is not None else f"return {curl_rc}"
        snippet = self._extract_preflight(START_SH.read_text())
        with tempfile.TemporaryDirectory() as d:
            harness = f"""
set -u
STATUS_SUPERSEDED_FILE="{Path(d) / 'superseded'}"
TUNNEL_URL="wss://allocator.example.com"
TUNNEL_PATH_PREFIX="tun-vm-1-abc"
TUNNEL_BIND_ADDR="127.0.0.10"
CLIENT_SECRET="cs"
send_status() {{ echo "STATUS_CALLED:$1"; return 0; }}
curl() {{ {stub}; }}
{snippet}
echo "REACHED_LAUNCH"
"""
            return subprocess.run(
                ["bash", "-c", harness], capture_output=True, text=True, timeout=30
            )

    def test_unreachable_allocator_fails_instead_of_declaring_a_live_tunnel(self):
        """The bug this preflight exists for, observed live 2026-07-31: with
        the allocator unreachable (a hostname resolving to an address this
        container cannot route to), wstunnel logs only "Opening TCP
        connection" per retry -- at INFO, no error line -- so every log-based
        check passes and the client announced a healthy tunnel that had never
        connected. Only a positive probe catches it."""
        result = self._run(curl_rc=7)  # curl(7): couldn't connect, as observed
        assert "STATUS_CALLED:error" in result.stdout, result.stdout
        assert "REACHED_LAUNCH" not in result.stdout, result.stdout
        assert "cannot reach the allocator" in result.stderr, result.stderr

    def test_reachable_allocator_proceeds_to_launch(self):
        """The probe must not become a new way to strand a healthy client."""
        result = self._run(curl_rc=0)
        assert "STATUS_CALLED:error" not in result.stdout, result.stdout
        assert "REACHED_LAUNCH" in result.stdout, result.stdout

    def test_readiness_503_still_counts_as_reachable(self):
        """The deadlock this probe caused, observed live 2026-07-31:
        /api/health answers 503 while THIS client's own tunnel is unattached,
        so a probe demanding 2xx could only pass once the tunnel was up --
        which the probe itself was blocking. Any HTTP answer proves
        reachability, which is all this check is entitled to ask.

        The stub fails exactly the way curl does when -f meets a 503 (exit 22)
        and succeeds otherwise, so this passes only if the probe drops -f."""
        result = self._run(
            curl_body='for a in "$@"; do case "$a" in -*f*) return 22;; esac; '
            "done; return 0"
        )
        assert "REACHED_LAUNCH" in result.stdout, result.stdout
        assert "STATUS_CALLED:error" not in result.stdout, result.stdout

    def test_failure_message_carries_curls_exit_code(self):
        """The live failure log said only "not reachable", which is a symptom.
        curl's exit code separates DNS (6) from no-route (7) from timeout (28)
        -- and `$?` read after `fi` would report the if statement's 0 instead,
        so this asserts the real code reaches the log."""
        result = self._run(curl_rc=6)
        assert "curl exit 6" in result.stdout, result.stdout
        # ...and a connectivity failure must keep pointing at DNS/routing —
        # the TLS branch below must not swallow this class.
        assert "cannot reach the allocator" in result.stderr, result.stderr
        assert "TLS handshake" not in result.stderr, result.stderr

    def test_self_signed_cert_still_counts_as_reachable(self):
        """The probe must not be stricter than the tunnel it gates.

        wstunnel does not verify server certificates -- v10.6.2's
        --tls-verify-certificate help: "Disabled by default. The client will
        happily connect to any server with self-signed certificate." -- and
        this branch passes no such flag. So an allocator on a self-signed or
        staging cert (ssl.staging, or the operator's own reverse proxy) must
        not abort a client whose tunnel would connect fine.

        The stub fails with curl's real cert-rejection code (60) unless -k is
        present, so this passes only if the probe actually sends -k.
        """
        result = self._run(
            curl_body='for a in "$@"; do case "$a" in -*k*) return 0;; esac; '
            "done; return 60"
        )
        assert "REACHED_LAUNCH" in result.stdout, result.stdout
        assert "STATUS_CALLED:error" not in result.stdout, result.stdout

    @pytest.mark.parametrize("rc", [35, 60])
    def test_tls_failure_is_not_diagnosed_as_dns(self, rc):
        """A TLS failure that survives -k is not a trust problem, so the
        abort must not send the operator to DNS and routing -- which is what
        the single catch-all message used to do for every exit code."""
        result = self._run(curl_rc=rc)
        assert "STATUS_CALLED:error" in result.stdout, result.stdout
        assert "TLS handshake" in result.stderr, result.stderr
        assert f"curl exit {rc}" in result.stderr, result.stderr
        assert "Check DNS and routing" not in result.stderr, result.stderr
