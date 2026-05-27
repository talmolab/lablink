"""KasmVNC password-file rotation.

Two output formats, picked by the client container's ``CONNECTIVITY`` env:

* ``allocator_proxied`` (AWS path; default): KasmVNC's username-based
  ``.kasmpasswd`` written by the bundled ``kasmvncpasswd`` CLI. The
  browser never sees credentials; allocator nginx attaches HTTP Basic
  Auth server-side via ``/internal/proxy_auth``.

* ``lan_direct`` (manual/BYO path): the browser opens the WebSocket
  straight to ``ws://<lan_ip>:6080`` with no proxy, and modern browsers
  refuse to attach an ``Authorization: Basic`` header to a WebSocket
  upgrade. So we drop HTTP-Basic on the client (``-DisableBasicAuth``)
  and use RFB-protocol ``VncAuth`` instead — KasmVNC's bundled noVNC
  reads ``?password=`` and feeds it through the in-band VNC auth
  handshake. That requires the legacy RFB password file format:
  8 bytes of single-DES-encrypted output, written here without an
  external ``vncpasswd`` tool (KasmVNC's deb doesn't ship one).

The agent re-derives the file each session; no reload signal is needed
(KasmVNC re-reads on each connection attempt, and SIGHUP would in fact
terminate Xvnc via its unsupported reset path).
"""
import os
import subprocess

from cryptography.hazmat.primitives.ciphers import Cipher, modes

try:
    # cryptography ≥ 45 — TripleDES is moved to a "decrepit" submodule
    # and emits a DeprecationWarning at the old location. Prefer this
    # path so we don't generate warnings on import in newer installs.
    from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
except ImportError:
    from cryptography.hazmat.primitives.ciphers.algorithms import TripleDES  # type: ignore[no-redef]


DEFAULT_PASSWORD_FILE = "/home/client/.kasmpasswd"
DEFAULT_VNCAUTH_FILE = "/home/client/.vnc/passwd"
KASMVNC_USERNAME = "kasm_user"

# The fixed DES key TigerVNC / KasmVNC use to obfuscate the stored
# password. Lifted verbatim from TigerVNC's `Password.cxx`
# (`ObfuscatedPasswd`): the password file's 8 bytes are
# ``DES_encrypt(key=this, plaintext=padded_password)`` and KasmVNC
# decrypts with this same key to recover the plaintext at auth time.
_VNCAUTH_FIXED_KEY = bytes(
    [0x17, 0x52, 0x6B, 0x06, 0x23, 0x4E, 0x58, 0x07]
)


def _password_file() -> str:
    return os.environ.get("KASMVNC_PASSWORD_FILE", DEFAULT_PASSWORD_FILE)


def _vncauth_file() -> str:
    return os.environ.get("KASMVNC_VNCAUTH_FILE", DEFAULT_VNCAUTH_FILE)


def _vncauth_blob(password: str) -> bytes:
    """Return the 8-byte payload that ``-PasswordFile`` consumes.

    VncAuth keys are exactly 8 bytes; we truncate longer passwords and
    NUL-pad shorter ones. The caller is responsible for keeping the
    plaintext within 8 characters; passing a longer string here silently
    drops the tail — the upstream protocol simply can't carry more.

    The standard DES library in ``cryptography`` is bit-compatible with
    the d3des routine TigerVNC uses, so we can drive it directly with
    the fixed key and the padded password as plaintext.

    ``cryptography`` removed plain DES; we get a single-DES block by
    passing a 24-byte 3DES key built from three copies of the 8-byte
    key (3DES-EDE with K1=K2=K3 collapses algebraically to single DES).
    """
    pw_bytes = (password.encode("utf-8") + b"\x00" * 8)[:8]
    cipher = Cipher(TripleDES(_VNCAUTH_FIXED_KEY * 3), modes.ECB())
    enc = cipher.encryptor()
    return enc.update(pw_bytes) + enc.finalize()


def _rotate_basic_auth(*, password: str) -> None:
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


def _rotate_vncauth(*, password: str) -> None:
    pw_file = _vncauth_file()
    pw_dir = os.path.dirname(pw_file) or "."
    os.makedirs(pw_dir, exist_ok=True)
    # Atomic-ish replace: write tempfile + rename, so Xvnc never reads a
    # half-written file under us. Same dir for the rename to stay on the
    # same filesystem.
    tmp = pw_file + ".tmp"
    with open(tmp, "wb") as f:
        f.write(_vncauth_blob(password))
    os.chmod(tmp, 0o600)
    os.replace(tmp, pw_file)


def rotate_kasmvnc_password(*, password: str) -> None:
    """Rewrite the KasmVNC password file for this connectivity mode.

    See module docstring for the two formats; the choice is driven by
    the ``CONNECTIVITY`` env var (``lan_direct`` ⇒ RFB VncAuth file;
    anything else, including unset ⇒ KasmVNC BasicAuth file).
    """
    if os.environ.get("CONNECTIVITY") == "lan_direct":
        _rotate_vncauth(password=password)
    else:
        _rotate_basic_auth(password=password)
