import subprocess
from unittest.mock import patch

import pytest


def test_rotate_invokes_kasmvncpasswd(tmp_path, monkeypatch):
    """allocator_proxied (default): rotate_kasmvnc_password shells out
    to kasmvncpasswd with the fixed username, password piped on stdin
    twice, and the configured target file. No reload signal is sent —
    KasmVNC re-reads the file on each Basic Auth check, and SIGHUP
    would terminate Xvnc via its unsupported reset path."""
    pw_file = tmp_path / "kasmvncpasswd"
    monkeypatch.setenv("KASMVNC_PASSWORD_FILE", str(pw_file))
    monkeypatch.delenv("CONNECTIVITY", raising=False)
    from lablink_client_service.agent.kasmvnc import (
        KASMVNC_USERNAME,
        rotate_kasmvnc_password,
    )
    with patch(
        "lablink_client_service.agent.kasmvnc.subprocess.run"
    ) as run:
        run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        rotate_kasmvnc_password(password="hunter2")
    assert run.call_count == 1
    args, kwargs = run.call_args
    assert args[0] == [
        "kasmvncpasswd", "-u", KASMVNC_USERNAME, "-rwo", str(pw_file),
    ]
    assert kwargs["input"] == "hunter2\nhunter2\n"
    assert kwargs["text"] is True


def test_rotate_raises_on_nonzero_exit(tmp_path, monkeypatch):
    """If kasmvncpasswd exits non-zero, the rotation raises."""
    pw_file = tmp_path / "kasmvncpasswd"
    monkeypatch.setenv("KASMVNC_PASSWORD_FILE", str(pw_file))
    monkeypatch.delenv("CONNECTIVITY", raising=False)
    from lablink_client_service.agent.kasmvnc import rotate_kasmvnc_password
    with patch(
        "lablink_client_service.agent.kasmvnc.subprocess.run"
    ) as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stderr="invalid user", stdout=""
        )
        with pytest.raises(RuntimeError, match="kasmvncpasswd failed"):
            rotate_kasmvnc_password(password="NEW")


def test_vncauth_blob_matches_tigervnc_vncpasswd():
    """The RFB-format ``.vnc/passwd`` file is exactly 8 bytes. Locks
    the encoding so a future algorithm tweak can't silently break the
    KasmVNC handshake — that's the failure mode that costs hours
    because KasmVNC just rejects auth with ``AuthFailureException`` /
    no diagnostic log line beyond that.

    Vector cross-verified against ``tigervncpasswd`` from the
    ``tigervnc-tools`` package on Ubuntu 22.04: for the password
    ``"abcd1234"``, vncpasswd writes ``237bbe0803430cc2``. The
    subtlety this catches: VNC's d3des reads key bytes LSB-first
    internally, so to produce the same output via a standard
    MSB-first DES library we bit-reverse the fixed key (only —
    the password as plaintext is not bit-reversed).
    """
    from lablink_client_service.agent.kasmvnc import _vncauth_blob
    assert _vncauth_blob("abcd1234").hex() == "237bbe0803430cc2"
    # Determinism: same input → same 8-byte output across calls.
    assert _vncauth_blob("abcd1234") == _vncauth_blob("abcd1234")


def test_vncauth_blob_truncates_to_8_chars():
    """VncAuth keys are 8 bytes. Passing a longer string drops the
    tail silently — by design, the protocol can't carry more — but
    must NOT raise, and the first-8-bytes prefix MUST drive the
    output identically to the equivalent 8-char input."""
    from lablink_client_service.agent.kasmvnc import _vncauth_blob
    assert _vncauth_blob("abcdefgh") == _vncauth_blob("abcdefgh_ignored")


def test_rotate_lan_direct_writes_vncauth_file(tmp_path, monkeypatch):
    """lan_direct: rotate_kasmvnc_password writes the 8-byte VncAuth
    blob to the configured file (mode 0600) and does NOT invoke
    kasmvncpasswd."""
    pw_file = tmp_path / "passwd"
    monkeypatch.setenv("KASMVNC_VNCAUTH_FILE", str(pw_file))
    monkeypatch.setenv("CONNECTIVITY", "lan_direct")
    from lablink_client_service.agent.kasmvnc import (
        _vncauth_blob,
        rotate_kasmvnc_password,
    )
    with patch(
        "lablink_client_service.agent.kasmvnc.subprocess.run"
    ) as run:
        rotate_kasmvnc_password(password="pwfor8ch")
        run.assert_not_called()
    assert pw_file.read_bytes() == _vncauth_blob("pwfor8ch")
    # mode bits low 9: rwxrwxrwx. 0600 = owner read+write only.
    assert (pw_file.stat().st_mode & 0o777) == 0o600
