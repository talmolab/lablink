import subprocess
from unittest.mock import patch

import pytest


def test_rotate_invokes_kasmvncpasswd(tmp_path, monkeypatch):
    """Happy path: rotate_kasmvnc_password shells out to kasmvncpasswd
    with the fixed username, password piped on stdin twice, and the
    configured target file. The reload SIGHUP follows on success."""
    pw_file = tmp_path / "kasmvncpasswd"
    monkeypatch.setenv("KASMVNC_PASSWORD_FILE", str(pw_file))
    from lablink_client_service.agent.kasmvnc import (
        KASMVNC_USERNAME,
        rotate_kasmvnc_password,
    )
    with patch(
        "lablink_client_service.agent.kasmvnc.subprocess.run"
    ) as run, patch(
        "lablink_client_service.agent.kasmvnc._signal_kasmvnc"
    ) as sig:
        run.return_value = subprocess.CompletedProcess(args=[], returncode=0)
        rotate_kasmvnc_password(password="hunter2")
    assert run.call_count == 1
    args, kwargs = run.call_args
    assert args[0] == [
        "kasmvncpasswd", "-u", KASMVNC_USERNAME, "-rwo", str(pw_file),
    ]
    assert kwargs["input"] == "hunter2\nhunter2\n"
    assert kwargs["text"] is True
    sig.assert_called_once()


def test_rotate_raises_on_nonzero_exit(tmp_path, monkeypatch):
    """If kasmvncpasswd exits non-zero, the rotation raises and the
    reload signal is NOT sent (we don't want to SIGHUP after a failed
    rewrite — kasmvncserver would re-read the previous, still-good file
    on the next legitimate rotation)."""
    pw_file = tmp_path / "kasmvncpasswd"
    monkeypatch.setenv("KASMVNC_PASSWORD_FILE", str(pw_file))
    from lablink_client_service.agent.kasmvnc import rotate_kasmvnc_password
    with patch(
        "lablink_client_service.agent.kasmvnc.subprocess.run"
    ) as run, patch(
        "lablink_client_service.agent.kasmvnc._signal_kasmvnc"
    ) as sig:
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stderr="invalid user", stdout=""
        )
        with pytest.raises(RuntimeError, match="kasmvncpasswd failed"):
            rotate_kasmvnc_password(password="NEW")
    sig.assert_not_called()
