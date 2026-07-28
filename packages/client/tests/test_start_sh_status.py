"""Tests for start.sh's VM-status reporting and startup ordering.

start.sh isn't sourceable as a whole (it `exec`s stdout through a tagger and
launches long-running services), so these tests extract the two self-contained
regions under test — the `send_status` helper and the `initializing` reporting
block — straight out of the real file and run them under bash with a stubbed
`curl`. Extraction is marker-based rather than line-based so it survives edits
elsewhere in the script.

The ordering tests assert against the real file directly: the Tailscale join
must precede every allocator call and the custom startup script, because on a
mesh-overlay deployment the tailnet can be the only route to the allocator
(so a pre-join POST fails outright, not merely races), and because a container
killed mid-startup-script would otherwise never join the overlay at all.
"""

import subprocess
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


@pytest.fixture(scope="module")
def status_block(script_text: str) -> str:
    """The status vars + send_status() + the `initializing` reporting block."""
    helper = _extract(script_text, "STATUS_SUPERSEDED_FILE=", "}")
    reporter = _extract(script_text, 'if ! send_status "initializing"; then', "fi")
    return f"{helper}\n\n{reporter}\n"


def _run(status_block: str, tmp_path: Path, *, fail: bool, **env) -> dict:
    """Run the extracted block with a stubbed curl. Returns paths + output."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    calls.write_text("")
    fail_flag = tmp_path / "fail"
    if fail:
        fail_flag.write_text("")

    # Stub curl: fails while the flag file exists, then succeeds. It does not
    # emulate curl's own --retry loop, so one invocation == one send_status.
    (bin_dir / "curl").write_text(
        "#!/bin/bash\n"
        f'echo call >> "{calls}"\n'
        f'if [ -f "{fail_flag}" ]; then\n'
        '  echo "curl: (7) Couldn\'t connect to server" >&2\n'
        "  exit 7\n"
        "fi\n"
        'echo \'{"message":"VM status updated successfully."}\'\n'
    )
    (bin_dir / "curl").chmod(0o755)

    script = tmp_path / "under_test.sh"
    script.write_text(status_block)
    out = tmp_path / "out"

    full_env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "ALLOCATOR_URL": "http://allocator.invalid",
        "CLIENT_SECRET": "secret",
        "VM_NAME": "vm-1",
        "STATUS_SUPERSEDED_FILE": str(tmp_path / "superseded"),
        **env,
    }
    # Redirect to a real file, not a pipe: the background retrier outlives this
    # call and would die on EPIPE if stdout were a closed pipe.
    with out.open("w") as fh:
        subprocess.run(
            ["bash", str(script)], env=full_env, stdout=fh, stderr=fh, check=False
        )
    return {
        "calls": calls,
        "out": out,
        "fail_flag": fail_flag,
        "superseded": Path(full_env["STATUS_SUPERSEDED_FILE"]),
    }


def _n_calls(paths: dict) -> int:
    return len([ln for ln in paths["calls"].read_text().splitlines() if ln])


def test_successful_report_posts_once_and_spawns_no_retrier(status_block, tmp_path):
    paths = _run(
        status_block,
        tmp_path,
        fail=False,
        STATUS_RETRY_INTERVAL_SECONDS="1",
        STATUS_RETRY_MAX_ATTEMPTS="5",
    )
    assert _n_calls(paths) == 1
    assert "retrying in background" not in paths["out"].read_text()
    # Nothing further should arrive: a retrier would have fired by now.
    subprocess.run(["sleep", "2"], check=True)
    assert _n_calls(paths) == 1


def test_failed_report_retries_in_background_until_it_lands(status_block, tmp_path):
    paths = _run(
        status_block,
        tmp_path,
        fail=True,
        STATUS_RETRY_INTERVAL_SECONDS="1",
        STATUS_RETRY_MAX_ATTEMPTS="20",
    )
    assert "retrying in background" in paths["out"].read_text()
    assert _n_calls(paths) == 1

    paths["fail_flag"].unlink()  # network comes back
    subprocess.run(["sleep", "3"], check=True)
    after = _n_calls(paths)
    assert after > 1, "background retrier never re-attempted"
    assert "VM status updated successfully" in paths["out"].read_text()

    # Having succeeded, the retrier must stop rather than keep posting.
    subprocess.run(["sleep", "2"], check=True)
    assert _n_calls(paths) == after


def test_superseded_sentinel_stops_retrier_without_posting_stale_status(
    status_block, tmp_path
):
    paths = _run(
        status_block,
        tmp_path,
        fail=True,
        STATUS_RETRY_INTERVAL_SECONDS="1",
        STATUS_RETRY_MAX_ATTEMPTS="20",
    )
    before = _n_calls(paths)
    paths["superseded"].write_text("")  # a later status ('running') won
    paths["fail_flag"].unlink()  # network is fine now
    subprocess.run(["sleep", "3"], check=True)
    assert _n_calls(paths) == before, "posted a stale 'initializing' after supersede"


def test_retrier_gives_up_after_max_attempts(status_block, tmp_path):
    paths = _run(
        status_block,
        tmp_path,
        fail=True,  # never recovers
        STATUS_RETRY_INTERVAL_SECONDS="1",
        STATUS_RETRY_MAX_ATTEMPTS="3",
    )
    subprocess.run(["sleep", "5"], check=True)
    assert "gave up reporting status=initializing" in paths["out"].read_text()
    assert _n_calls(paths) == 4, "expected 1 inline attempt + 3 bounded retries"


def test_stale_sentinel_from_a_previous_run_does_not_disable_retrier(
    status_block, tmp_path
):
    """`docker restart` re-runs start.sh against the same filesystem, so a
    sentinel written by the previous run is still on disk. If it were not
    cleared, the retrier would exit on its first tick on every boot after the
    first — disabling itself precisely on a crash-looping client."""
    stale = tmp_path / "superseded"
    stale.write_text("")  # left over from a previous run
    paths = _run(
        status_block,
        tmp_path,
        fail=True,
        STATUS_SUPERSEDED_FILE=str(stale),
        STATUS_RETRY_INTERVAL_SECONDS="1",
        STATUS_RETRY_MAX_ATTEMPTS="20",
    )
    assert not stale.exists(), "start.sh must clear the sentinel at startup"
    paths["fail_flag"].unlink()
    subprocess.run(["sleep", "3"], check=True)
    assert _n_calls(paths) > 1, "stale sentinel silenced the background retrier"


def test_send_status_returns_curl_exit_status(script_text):
    """The helper must not swallow failures with a trailing `|| echo`, or
    callers can't tell a lost report from a delivered one."""
    helper = _extract(script_text, "STATUS_SUPERSEDED_FILE=", "}")
    assert "|| echo" not in helper


class TestStartupOrdering:
    """Guards the ordering fix: overlay join, then status, then startup script."""

    @staticmethod
    def _line_of(text: str, needle: str) -> int:
        for i, ln in enumerate(text.splitlines()):
            if needle in ln:
                return i
        raise AssertionError(f"{needle!r} not found in start.sh")

    def test_tailscale_join_precedes_first_allocator_call(self, script_text):
        join = self._line_of(script_text, "tailscale up --authkey=")
        first_status = self._line_of(script_text, 'if ! send_status "initializing"')
        assert join < first_status, (
            "the overlay join must run before any allocator POST — on a "
            "mesh-overlay deployment the tailnet may be the only route"
        )

    def test_tailscale_join_precedes_custom_startup_script(self, script_text):
        join = self._line_of(script_text, "tailscale up --authkey=")
        startup = self._line_of(script_text, "Running custom startup script")
        assert join < startup, (
            "the overlay join must not sit behind the startup script: a "
            "container killed mid-script would never join the overlay"
        )

    def test_running_supersedes_initializing_before_posting(self, script_text):
        """`running` must mark the sentinel first, or an in-flight retrier can
        overwrite the newer status with the older one."""
        lines = script_text.splitlines()
        running = self._line_of(script_text, 'send_status "running"')
        touches = [
            i
            for i, ln in enumerate(lines)
            if 'touch "$STATUS_SUPERSEDED_FILE"' in ln and i < running
        ]
        assert touches, "no supersede marker before send_status \"running\""
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
        gate = self._line_of(script_text, 'if [ -n "$TAILSCALE_AUTHKEY" ]; then')
        join = self._line_of(script_text, "tailscale up --authkey=")
        daemon = self._line_of(script_text, "sudo tailscaled")
        assert gate < daemon < join, "tailscaled/join escaped the authkey gate"
        # ...and the gate must close before the startup script runs.
        closing = next(i for i in range(join, len(lines)) if lines[i] == "fi")
        assert closing < self._line_of(script_text, "Running custom startup script")

    def test_join_failure_reports_error_status(self, script_text):
        """A failed join must still try to tell the allocator before exiting."""
        block = script_text[script_text.index("tailscale up --authkey=") :]
        block = block[: block.index("\nfi\n")]
        assert 'send_status "error"' in block
        assert "exit 1" in block
