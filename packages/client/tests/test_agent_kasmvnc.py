from unittest.mock import patch

import pytest


def test_rotate_writes_password_atomically(tmp_path, monkeypatch):
    pw_file = tmp_path / "kasmvncpasswd"
    monkeypatch.setenv("KASMVNC_PASSWORD_FILE", str(pw_file))
    from lablink_client_service.agent.kasmvnc import rotate_kasmvnc_password
    with patch("lablink_client_service.agent.kasmvnc._signal_kasmvnc") as sig:
        rotate_kasmvnc_password(password="hunter2")
    assert pw_file.read_text().strip() == "hunter2"
    sig.assert_called_once()
    mode = pw_file.stat().st_mode & 0o777
    assert mode == 0o600


def test_rotate_replaces_existing_file(tmp_path, monkeypatch):
    pw_file = tmp_path / "kasmvncpasswd"
    pw_file.write_text("OLD\n")
    monkeypatch.setenv("KASMVNC_PASSWORD_FILE", str(pw_file))
    from lablink_client_service.agent.kasmvnc import rotate_kasmvnc_password
    with patch("lablink_client_service.agent.kasmvnc._signal_kasmvnc",
               side_effect=RuntimeError("nope")):
        with pytest.raises(RuntimeError):
            rotate_kasmvnc_password(password="NEW")
    # File was replaced before the signal step — signal failure
    # doesn't undo the file write.
    assert pw_file.read_text().strip() == "NEW"
