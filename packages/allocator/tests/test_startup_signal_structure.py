"""Structural tests for the VM startup-signal reporting.

These are not full Terraform rendering tests or bash-execution tests —
they verify the source files' textual structure to prevent regressions
where the `status='running'` signal gets re-added to user_data.sh
prematurely (before container startup completes), or where start.sh
forgets to report readiness/failure.

If full Terraform template rendering is ever added to this repo, the
user_data.sh checks below can be upgraded to run against the rendered
artifact instead. For bash execution, a bats-based suite would be the
upgrade path.
"""

from pathlib import Path


PACKAGES_ROOT = Path(__file__).resolve().parent.parent.parent
USER_DATA_PATH = (
    PACKAGES_ROOT
    / "allocator"
    / "src"
    / "lablink_allocator_service"
    / "terraform"
    / "user_data.sh"
)
START_SH_PATH = PACKAGES_ROOT / "client" / "start.sh"


def _read_user_data() -> str:
    assert USER_DATA_PATH.is_file(), (
        f"user_data.sh not found: {USER_DATA_PATH}"
    )
    return USER_DATA_PATH.read_text()


def _read_start_sh() -> str:
    assert START_SH_PATH.is_file(), f"start.sh not found: {START_SH_PATH}"
    return START_SH_PATH.read_text()


# ---------------------------------------------------------------------------
# user_data.sh: the premature 'running' signal has been moved elsewhere
# ---------------------------------------------------------------------------


def test_user_data_reports_initializing_at_start():
    """The initializing signal must still fire from cloud-init."""
    content = _read_user_data()
    assert 'send_status "initializing"' in content, (
        "user_data.sh must report 'initializing' so the allocator knows "
        "cloud-init has started."
    )


def test_user_data_does_not_report_running_after_docker_run():
    """The 'running' signal has been moved to start.sh.

    Before this fix, user_data.sh set status='running' the instant
    docker run returned — before the container's own startup (custom
    startup script, client services) had finished. This masked the
    difference between "container exists" and "client ready for
    students". Readiness is now reported by start.sh.
    """
    content = _read_user_data()
    assert 'send_status "running"' not in content, (
        "user_data.sh must NOT report 'running' — that signal now lives "
        "in start.sh. See the 2026-04-15 follow-up PR rationale."
    )


def test_user_data_still_reports_error_on_failure():
    """Cloud-init failures must still surface as status='error'."""
    content = _read_user_data()
    assert 'send_status "error"' in content, (
        "user_data.sh must still report 'error' on cloud-init failure."
    )


# ---------------------------------------------------------------------------
# start.sh: readiness and startup-failure reporting
# ---------------------------------------------------------------------------


def test_start_sh_has_send_status_helper():
    """start.sh defines a send_status helper DRYing up the status POSTs."""
    content = _read_start_sh()
    assert "send_status()" in content, (
        "start.sh should define a send_status shell helper so the two "
        "status POSTs (running, error) share one implementation."
    )
    assert "/api/vm-status" in content, (
        "send_status helper must POST to /api/vm-status."
    )


def test_start_sh_reports_running_before_service_launches():
    """start.sh must call send_status running before launching subscribe."""
    content = _read_start_sh()
    lines = content.splitlines()
    running_line = None
    subscribe_line = None
    for i, line in enumerate(lines):
        if 'send_status "running"' in line and running_line is None:
            running_line = i
        # The subscribe service launch is the first standalone `subscribe \`
        # invocation (not inside a function body, not in a comment).
        if line.strip().startswith("subscribe \\") and subscribe_line is None:
            subscribe_line = i

    assert running_line is not None, (
        "start.sh must call send_status running."
    )
    assert subscribe_line is not None, (
        "start.sh must launch the subscribe service."
    )
    assert running_line < subscribe_line, (
        f"send_status running must be called before subscribe launches "
        f"(found running at line {running_line + 1}, subscribe at line "
        f"{subscribe_line + 1})."
    )


def test_start_sh_reports_error_on_fail_branch():
    """start.sh must call send_status error before exiting on startup failure.

    Without this, a VM whose custom-startup fails with
    STARTUP_ON_ERROR=fail would stay in 'initializing' until the
    stale-initializing timer (25 min) triggered a reboot — leaving
    admins blind to the failure for the duration.
    """
    content = _read_start_sh()
    assert "STARTUP_ON_ERROR" in content, (
        "start.sh should branch on STARTUP_ON_ERROR."
    )
    # Find the STARTUP_ON_ERROR check block and ensure send_status "error"
    # appears inside it, before the exit.
    idx = content.find("STARTUP_ON_ERROR")
    exit_idx = content.find("exit", idx)
    assert exit_idx > idx > -1, (
        "Could not locate the STARTUP_ON_ERROR fail-branch block."
    )
    fail_branch = content[idx:exit_idx]
    assert 'send_status "error"' in fail_branch, (
        "The STARTUP_ON_ERROR=fail branch must call send_status error "
        "before exiting, so the allocator learns of the failure "
        "immediately instead of waiting out the stale-initializing "
        "timeout."
    )
