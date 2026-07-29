"""Structural tests for start.sh's startup ordering and status reporting.

start.sh isn't sourceable as a whole — it `exec`s stdout through a tagger and
launches long-running services — so these assert against the script text
rather than executing it. That keeps them instant and free of timing
dependence; the runtime behaviour of the background status retrier was
verified by hand instead.

What they protect is the ordering, which is where the bug was: the Tailscale
join must precede every allocator call and the custom startup script, because
on a mesh-overlay deployment the tailnet can be the only route to the
allocator (so a pre-join POST fails outright, not merely races), and because a
container killed mid-startup-script would otherwise never join the overlay at
all. Each assertion below was checked against reconstructed pre-fix code to
confirm it actually fails on it.
"""

from pathlib import Path

import pytest

START_SH = Path(__file__).resolve().parents[1] / "start.sh"


@pytest.fixture(scope="module")
def script_text() -> str:
    return START_SH.read_text()


def _extract(text: str, first_line_startswith: str, closer: str) -> str:
    """Return lines from the first line starting with `first_line_startswith`
    through the next line equal to `closer` (inclusive)."""
    lines = text.splitlines()
    start = next(
        i for i, ln in enumerate(lines) if ln.startswith(first_line_startswith)
    )
    end = next(i for i in range(start, len(lines)) if lines[i] == closer)
    return "\n".join(lines[start : end + 1])


def _line_of(text: str, needle: str) -> int:
    for i, ln in enumerate(text.splitlines()):
        if needle in ln:
            return i
    raise AssertionError(f"{needle!r} not found in start.sh")


def test_send_status_returns_curl_exit_status(script_text):
    """The helper must not swallow failures with a trailing `|| echo`, or
    callers can't tell a lost report from a delivered one — which is what let
    a failed 'initializing' pass silently."""
    helper = _extract(script_text, "STATUS_SUPERSEDED_FILE=", "}")
    assert "|| echo" not in helper


def test_supersede_sentinel_is_cleared_at_startup(script_text):
    """`docker restart` re-runs start.sh against the same filesystem, so /tmp
    still holds a sentinel written by the previous run. Unless it is cleared
    first, the retrier exits on its first tick on every boot after the first —
    silently disabling itself on exactly the crash-looping client it exists
    for. The clear must come before anything reads or writes the sentinel."""
    clear = _line_of(script_text, 'rm -f "$STATUS_SUPERSEDED_FILE"')
    first_read = _line_of(script_text, '[ -f "$STATUS_SUPERSEDED_FILE" ]')
    first_touch = _line_of(script_text, 'touch "$STATUS_SUPERSEDED_FILE"')
    assert clear < first_read
    assert clear < first_touch


class TestStartupOrdering:
    """Guards the ordering fix: overlay join, then status, then startup script."""

    def test_tailscale_join_precedes_first_allocator_call(self, script_text):
        join = _line_of(script_text, "tailscale up --authkey=")
        first_status = _line_of(script_text, 'if ! send_status "initializing"')
        assert join < first_status, (
            "the overlay join must run before any allocator POST — on a "
            "mesh-overlay deployment the tailnet may be the only route"
        )

    def test_tailscale_join_precedes_custom_startup_script(self, script_text):
        join = _line_of(script_text, "tailscale up --authkey=")
        startup = _line_of(script_text, "Running custom startup script")
        assert join < startup, (
            "the overlay join must not sit behind the startup script: a "
            "container killed mid-script would never join the overlay"
        )

    def test_running_supersedes_initializing_before_posting(self, script_text):
        """`running` must mark the sentinel first, or an in-flight retrier can
        overwrite the newer status with the older one."""
        lines = script_text.splitlines()
        running = _line_of(script_text, 'send_status "running"')
        touches = [
            i
            for i, ln in enumerate(lines)
            if 'touch "$STATUS_SUPERSEDED_FILE"' in ln and i < running
        ]
        assert touches, 'no supersede marker before send_status "running"'
        assert running - max(touches) <= 2, (
            "the supersede marker should immediately precede the 'running' post"
        )

    def test_join_block_stays_gated_on_authkey(self, script_text):
        """Blast-radius guard for moving the join earlier. AWS
        (allocator_proxied) and lan_direct clients never get TAILSCALE_AUTHKEY
        — `lablink register` writes it only alongside OVERLAY_HOSTNAME — so the
        whole block must remain inside that gate. Were it ever unconditional,
        every non-overlay client would newly pay a `tailscale up` failure
        before reporting any status at all."""
        lines = script_text.splitlines()
        gate = _line_of(script_text, 'if [ -n "$TAILSCALE_AUTHKEY" ]; then')
        join = _line_of(script_text, "tailscale up --authkey=")
        daemon = _line_of(script_text, "sudo tailscaled")
        assert gate < daemon < join, "tailscaled/join escaped the authkey gate"
        # ...and the gate must close before the startup script runs.
        closing = next(i for i in range(join, len(lines)) if lines[i] == "fi")
        assert closing < _line_of(script_text, "Running custom startup script")

    def test_join_failure_reports_error_status(self, script_text):
        """A failed join must still try to tell the allocator before exiting."""
        block = script_text[script_text.index("tailscale up --authkey=") :]
        block = block[: block.index("\nfi\n")]
        assert 'send_status "error"' in block
        assert "exit 1" in block


def test_overlay_hostname_read_back_after_join(script_text):
    """`tailscale up --hostname=X` exits 0 even when Tailscale renamed the
    node to X-1, so the assigned name must be read back from the daemon,
    not assumed (lablink#404)."""
    assert "tailscale status --json" in script_text
    assert "Self" in script_text and "DNSName" in script_text


def test_overlay_hostname_reported_to_dedicated_endpoint(script_text):
    """Must NOT ride on /api/vm-status — that endpoint and send_status are
    shared with the AWS path, where a lost status POST is unrecoverable."""
    assert "/api/overlay-hostname" in script_text
    send_status_body = _extract(script_text, "send_status() {", "}")
    # Comments are stripped first: send_status's own comment legitimately
    # discusses mesh-overlay clients (it explains why it needs --retry).
    # What must not appear is overlay *code* — a second endpoint or an
    # extra payload field on the AWS-shared status POST.
    code = "\n".join(
        ln for ln in send_status_body.splitlines()
        if not ln.strip().startswith("#")
    )
    assert "overlay" not in code.lower()


def test_overlay_report_is_inside_the_tailscale_gate(script_text):
    """All of it sits inside `if [ -n "$TAILSCALE_AUTHKEY" ]`, so an AWS or
    lan_direct client executes none of it."""
    gate = _line_of(script_text, 'if [ -n "$TAILSCALE_AUTHKEY" ]')
    report = _line_of(script_text, "/api/overlay-hostname")
    initializing = _line_of(script_text, 'send_status "initializing"')
    assert gate < report < initializing


def test_overlay_report_retries(script_text):
    """A lost report strands the allocator on the old name, so the immediate
    attempt must be retried rather than abandoned."""
    report = _line_of(script_text, "/api/overlay-hostname")
    window = "\n".join(script_text.splitlines()[report - 6 : report + 12])
    assert "--retry" in window
