import subprocess
from unittest.mock import patch

import pytest


def test_rotate_invokes_kasmvncpasswd(tmp_path, monkeypatch):
    """Happy path: rotate_kasmvnc_password shells out to kasmvncpasswd
    with the fixed username, password piped on stdin twice, and the
    configured target file. No reload signal is sent — KasmVNC re-reads
    the file on each Basic Auth check, and SIGHUP would terminate Xvnc
    via its unsupported reset path."""
    pw_file = tmp_path / "kasmvncpasswd"
    monkeypatch.setenv("KASMVNC_PASSWORD_FILE", str(pw_file))
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
    from lablink_client_service.agent.kasmvnc import rotate_kasmvnc_password
    with patch(
        "lablink_client_service.agent.kasmvnc.subprocess.run"
    ) as run:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stderr="invalid user", stdout=""
        )
        with pytest.raises(RuntimeError, match="kasmvncpasswd failed"):
            rotate_kasmvnc_password(password="NEW")
