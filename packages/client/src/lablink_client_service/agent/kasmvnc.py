"""KasmVNC password-file rotation.

KasmVNC's auth model is username-based: kasmvncpasswd writes an encoded
entry keyed by username. We use a single fixed username ("kasm_user") and
rotate only the password. The browser later authenticates over WebSocket
with HTTP Basic Auth (`kasm_user:<password>`), attached server-side by
nginx after auth_request approves the session.
"""
import os
import subprocess


DEFAULT_PASSWORD_FILE = "/home/client/.kasmpasswd"
KASMVNC_USERNAME = "kasm_user"


def _password_file() -> str:
    return os.environ.get("KASMVNC_PASSWORD_FILE", DEFAULT_PASSWORD_FILE)


def rotate_kasmvnc_password(*, password: str) -> None:
    """Rewrite the KasmVNC password file for the fixed username.

    KasmVNC re-reads `.kasmpasswd` on every HTTP Basic Auth check, so a
    plain file rewrite is enough; no reload signal is needed. (Sending
    SIGHUP to Xvnc would in fact terminate it — Xvnc treats SIGHUP as
    "reset the X server", the VNC extension can't be reset, and the X
    core falls back to terminating the process.)

    Delegates to the `kasmvncpasswd` CLI, which encodes the password
    using KasmVNC's expected format and (per its man page) replaces
    the target file atomically.
    """
    pw_file = _password_file()
    pw_dir = os.path.dirname(pw_file) or "."
    os.makedirs(pw_dir, exist_ok=True)
    result = subprocess.run(
        ["kasmvncpasswd", "-u", KASMVNC_USERNAME, "-rwo", pw_file],
        input=f"{password}\n{password}\n",
        text=True,
        capture_output=True,
        timeout=5,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"kasmvncpasswd failed (exit {result.returncode}): "
            f"{result.stderr.strip() or result.stdout.strip()}"
        )
