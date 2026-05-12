"""KasmVNC password-file rotation."""
import os
import subprocess
import tempfile


DEFAULT_PASSWORD_FILE = "/home/client/.kasmvnc/kasmvncpasswd"


def _password_file() -> str:
    return os.environ.get("KASMVNC_PASSWORD_FILE", DEFAULT_PASSWORD_FILE)


def _signal_kasmvnc() -> None:
    """Send SIGHUP to the running kasmvncserver process so it re-reads
    its password file. `check=False` so a missing process (in tests
    or before first launch) doesn't crash the agent."""
    subprocess.run(["pkill", "-HUP", "-x", "kasmvncserver"], check=False)


def rotate_kasmvnc_password(*, password: str) -> None:
    """Atomically replace the KasmVNC password file and signal reload.

    Atomicity: write to a sibling temp file, fsync, then os.replace
    (POSIX rename(2) is atomic on the same filesystem).
    Permissions: 0600 so other local users can't read it.
    """
    pw_file = _password_file()
    pw_dir = os.path.dirname(pw_file) or "."
    os.makedirs(pw_dir, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=pw_dir, prefix=".kasmvncpasswd.")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(password + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, pw_file)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise
    _signal_kasmvnc()
