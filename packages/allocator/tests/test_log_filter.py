"""Errors-only filtering of the log streams."""

from pathlib import Path

import pytest

from lablink_allocator_service.utils.log_filter import (
    BENIGN_CLIENT_PATTERNS,
    BENIGN_ERROR_PATTERNS,
    filter_errors,
    is_error_line,
)

# tests -> allocator -> packages. Verified, not assumed: parents[3] is the
# repo root, where there is no `client/`, so the skipif below would have
# skipped this file's drift test forever.
CLIENT_SRC = Path(__file__).parents[2] / "client" / "src"


def test_keeps_error_lines_and_drops_the_rest():
    text = "\n".join([
        "2026-08-14 12:00:00 - app - INFO - serving on :5000",
        "2026-08-14 12:00:01 - app - ERROR - database is on fire",
        "2026-08-14 12:00:02 - app - DEBUG - tick",
    ])
    assert filter_errors(text) == (
        "2026-08-14 12:00:01 - app - ERROR - database is on fire"
    )


def test_keeps_critical_and_fatal():
    text = "CRITICAL disk full\nFATAL cannot bind\nINFO fine"
    assert filter_errors(text) == "CRITICAL disk full\nFATAL cannot bind"


def test_excludes_warning():
    text = "2026-08-14 12:00:00 WARNING nvidia-smi not found\nINFO fine"
    assert filter_errors(text) == ""


def test_is_case_sensitive_so_the_startup_scripts_happy_path_is_excluded():
    """start.sh says `--retry-all-errors` and `status=error` on success
    paths; a case-insensitive rule would show them as errors."""
    assert not is_error_line("[start] curl --retry-all-errors ...")
    assert not is_error_line('[start] send_status "error" || echo ...')
    assert not is_error_line("[start] >> WARNING: failed to report status=error")


def test_drops_every_benign_retry_error():
    text = "\n".join([
        "2026-08-14T12:00:00Z [check_gpu] 12:00 ERROR check_gpu: "
        "Failed to report GPU health after 3 attempts",
        "2026-08-14T12:00:01Z [update_inuse_status] 12:00 ERROR u: "
        "Failed to update in-use status after 3 attempts",
        "2026-08-14T12:00:03Z [monitoring] 12:00 ERROR m: "
        "Push failed; will retry next interval",
        "2026-08-14T12:00:04Z [agent] 12:00 ERROR a: real problem",
    ])
    assert filter_errors(text) == (
        "2026-08-14T12:00:04Z [agent] 12:00 ERROR a: real problem"
    )


@pytest.mark.parametrize("pattern", BENIGN_ERROR_PATTERNS)
def test_every_benign_pattern_is_suppressed(pattern):
    """Covers a newly added pattern automatically, unlike a count check."""
    assert filter_errors(f"12:00 ERROR svc: {pattern} tail") == ""


@pytest.mark.skipif(not CLIENT_SRC.exists(), reason="client package not in checkout")
@pytest.mark.parametrize("pattern", BENIGN_CLIENT_PATTERNS)
def test_benign_pattern_still_exists_in_client_source(pattern):
    """A renamed client log message must fail here, not drift silently.

    Only BENIGN_CLIENT_PATTERNS are ours; BENIGN_NOISE_PATTERNS come from
    third-party binaries (X11/ICE) and are deliberately not drift-checked.
    """
    hits = [p for p in CLIENT_SRC.rglob("*.py") if pattern in p.read_text()]
    assert hits, f"{pattern!r} no longer appears in the client source"


def test_x11_socket_dir_notice_is_not_an_error():
    """The X11/ICE transport prints the literal word `ERROR` when it cannot
    make its socket dir as non-root -- benign, and on a healthy VM it is the
    entire errors-only view. Both real lines (observed live 2026-08-17)
    share the `ERROR: euid != 0` substring."""
    xserv = (
        "2026-08-17T16:41:00Z [kasmvnc] _XSERVTransmkdir: ERROR: euid != 0,"
        "directory /tmp/.X11-unix will not be created."
    )
    ice = (
        "2026-08-17T16:41:01Z [xstartup] _IceTransmkdir: ERROR: euid != 0,"
        "directory /tmp/.ICE-unix will not be created."
    )
    assert not is_error_line(xserv)
    assert not is_error_line(ice)
    # A real client ERROR (Hydra format `[LEVEL]`) still survives alongside.
    real = (
        "2026-08-17T16:41:02Z [check_gpu] [2026-08-17 16:41:02,505]"
        "[lablink_client_service.check_gpu][ERROR] - GPU status: Unhealthy"
    )
    assert filter_errors("\n".join([xserv, ice, real])) == real


def test_a_real_gpu_failure_is_not_suppressed():
    """check_gpu.py's `nvidia-smi failed:` branch is the one that sets
    status=Unhealthy, and its body carries nvidia-smi's own stderr -- the
    diagnosis an admin opens the errors-only view to find. The
    drivers-not-installed cases log at WARNING instead, so they are already
    excluded without a denylist entry."""
    assert is_error_line(
        "[check_gpu] 12:00 ERROR check_gpu: nvidia-smi failed: no devices found"
    )


def test_keeps_traceback_frames_and_the_terminal_line():
    text = "\n".join([
        "2026-08-14 12:00:00 - app - ERROR - boom",
        "Traceback (most recent call last):",
        '  File "/app/x.py", line 3, in go',
        "    raise ValueError('nope')",
        "ValueError: nope",
        "2026-08-14 12:00:01 - app - INFO - carrying on",
    ])
    assert filter_errors(text) == "\n".join([
        "2026-08-14 12:00:00 - app - ERROR - boom",
        "Traceback (most recent call last):",
        '  File "/app/x.py", line 3, in go',
        "    raise ValueError('nope')",
        "ValueError: nope",
    ])


def test_keeps_traceback_frames_behind_shipper_prefixes():
    """Client lines arrive as `<ts> [tag] ...` (log_shipper.py:284 plus
    start.sh's sed tags), so frames do not start at column 0."""
    text = "\n".join([
        "2026-08-14T12:00:00Z [agent] 12:00 ERROR a: boom",
        "2026-08-14T12:00:00Z [agent] Traceback (most recent call last):",
        '2026-08-14T12:00:00Z [agent]   File "/app/x.py", line 3, in go',
        "2026-08-14T12:00:00Z [agent] ValueError: nope",
        "2026-08-14T12:00:01Z [agent] 12:00 INFO a: carrying on",
    ])
    assert filter_errors(text) == "\n".join([
        "2026-08-14T12:00:00Z [agent] 12:00 ERROR a: boom",
        "2026-08-14T12:00:00Z [agent] Traceback (most recent call last):",
        '2026-08-14T12:00:00Z [agent]   File "/app/x.py", line 3, in go',
        "2026-08-14T12:00:00Z [agent] ValueError: nope",
    ])


def test_drops_the_traceback_of_a_benign_error():
    text = "\n".join([
        "12:00 ERROR m: Push failed; will retry next interval",
        "Traceback (most recent call last):",
        '  File "/app/p.py", line 9, in push',
        "ConnectionError: refused",
        "12:00 INFO m: next tick",
    ])
    assert filter_errors(text) == ""


def test_none_passes_through():
    """None means there is no log at all; the caller renders that
    differently from a log with no errors in it."""
    assert filter_errors(None) is None


def test_no_errors_yields_empty_string():
    assert filter_errors("INFO all good\nDEBUG tick") == ""


def test_interleaved_foreign_line_does_not_end_the_traceback():
    """start.sh:14 dups stdout to fd 5 and every service then pipes through
    its own `sed 's/^/[tag] /' >&5 &`, so a [kasmvnc] line landing inside an
    [agent] traceback is the normal condition, not a corner case."""
    text = "\n".join([
        "[agent] 12:00 ERROR a: boom",
        "[agent] Traceback (most recent call last):",
        "[kasmvnc] Framebuffer resize to 1920x1080",
        '[agent]   File "/app/x.py", line 3, in go',
        "[agent] ValueError: nope",
        "[agent] 12:00 INFO a: carrying on",
    ])
    out = filter_errors(text)
    assert out == "\n".join([
        "[agent] 12:00 ERROR a: boom",
        "[agent] Traceback (most recent call last):",
        '[agent]   File "/app/x.py", line 3, in go',
        "[agent] ValueError: nope",
    ])
    # The bug this guards: the resize was presented AS the exception.
    assert "[kasmvnc]" not in out


def test_an_interleaved_foreign_error_is_still_kept_on_its_own_account():
    """Stepping over a foreign line inside a traceback walk must not
    swallow it when it is itself an error."""
    text = "\n".join([
        "[agent] 12:00 ERROR a: boom",
        "[agent] Traceback (most recent call last):",
        "[kasmvnc] 12:00 ERROR kasm: no framebuffer",
        '[agent]   File "/app/x.py", line 3, in go',
        "[agent] ValueError: nope",
    ])
    assert filter_errors(text) == text


def test_a_foreign_line_is_never_presented_as_the_exception():
    """With no frame consumed there is nothing to attach, so the frame-count
    guard must leave the next line alone even when the tag cannot resolve
    it (here: an untagged stream, where any indented line is a frame)."""
    text = "\n".join([
        "12:00 ERROR a: boom",
        "Traceback (most recent call last):",
        "Framebuffer resize to 1920x1080",
    ])
    assert filter_errors(text) == "\n".join([
        "12:00 ERROR a: boom",
        "Traceback (most recent call last):",
    ])


def test_chained_traceback_keeps_the_outer_exception():
    """requests re-raises inside an `except`, so every logger.exception
    around an HTTP call chains. The second half's final line is the useful
    one -- it names the host and port."""
    text = "\n".join([
        "12:00 ERROR h: heartbeat failed",
        "Traceback (most recent call last):",
        '  File "/app/h.py", line 5, in send',
        "ConnectionRefusedError: [Errno 111] Connection refused",
        "",
        "During handling of the above exception, another exception occurred:",
        "",
        "Traceback (most recent call last):",
        '  File "/app/h.py", line 9, in beat',
        "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='a')",
        "12:00 INFO h: next tick",
    ])
    assert filter_errors(text) == "\n".join(text.splitlines()[:-1])


def test_chained_traceback_survives_an_interleaved_line_in_the_gap():
    """The direct-cause marker, behind shipper tags, with a foreign line in
    the two-line gap between the halves."""
    text = "\n".join([
        "[agent] 12:00 ERROR a: rotation failed",
        "[agent] Traceback (most recent call last):",
        '[agent]   File "/app/k.py", line 2, in rotate',
        "[agent] KeyError: 'pw'",
        "[agent] ",
        "[xstartup] xfce4-session: starting",
        "[agent] The above exception was the direct cause of the following "
        "exception:",
        "[agent] ",
        "[agent] Traceback (most recent call last):",
        '[agent]   File "/app/k.py", line 9, in start',
        "[agent] RuntimeError: could not rotate the session password",
    ])
    out = filter_errors(text)
    assert out.endswith("[agent] RuntimeError: could not rotate the session password")
    assert "[xstartup]" not in out


def test_keeps_cloudflared_and_postgres_levels():
    """cloudflared runs in the allocator container with its output teed into
    the same allocator.log (start.sh:153) and uses zerolog's three-letter
    levels; postgres says PANIC."""
    text = "\n".join([
        "2026-08-14T12:00:00Z ERR Failed to serve quic connection",
        "2026-08-14T12:00:01Z FTL Register tunnel error: dial tcp: refused",
        "2026-08-14 12:00:02 UTC [42] PANIC: could not write to file",
        "2026-08-14T12:00:03Z INF Connection established",
    ])
    assert filter_errors(text) == "\n".join(text.splitlines()[:-1])


def test_stderr_substring_alone_is_not_an_error():
    """`\\bERR\\b` must not fire inside STDERR -- no word boundary there."""
    assert not is_error_line("[start] redirecting STDERR through the tagger")
    assert not is_error_line("2026-08-14T12:00:00Z INF wrote 2 lines to STDERR")
