import argparse
import glob
import pwd
import socket
import subprocess
import logging
import time
import os


# Set up logging
logger = logging.getLogger(__name__)

# CRD writes a host#<hash>.json here after a successful auth-code exchange.
# Its presence on container restart means the host is already registered —
# re-running start-host would fail (code consumed / host already registered),
# so we restart the daemon instead. Destroyed on cold reboot (fresh container).
CRD_HOST_CONFIG_GLOB = "/home/client/.config/chrome-remote-desktop/host#*.json"


def set_logger(external_logger):
    global logger
    logger = external_logger


def cleanup_logs():
    try:
        for handler in logger.handlers:
            if hasattr(handler, "flush"):
                handler.flush()

        time.sleep(1.5)

        logging.shutdown()
    except Exception as e:
        logger.error(f"Error during log cleanup: {e}")


def create_parser() -> argparse.ArgumentParser:
    """Creates a parser for the command line arguments.

    Returns:
        argparse.ArgumentParser: The parser for the command line arguments.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--code",
        help="Unique code to allow connection via CRD with specific Google login.",
        type=str,
        default=None,
    )

    return parser


def construct_command(args) -> list[str]:
    """Build the start-host argv to register this VM with CRD.

    Returns a list for subprocess with ``shell=False``; ``DISPLAY`` is set
    via the environment by the caller rather than as a shell prefix. A
    single pair of matching surrounding quotes is stripped from the
    code (Google's copy-pasteable command wraps it in double quotes).
    Input validation of the code itself happens at the allocator in
    ``check_crd_input``; with ``shell=False`` here, any stray
    metacharacters would be passed as a literal argument to start-host
    rather than interpreted by a shell.
    """

    redirect_url = "https://remotedesktop.google.com/_/oauthredirect"
    name = os.getenv("VM_NAME") or socket.gethostname()

    if args.code is None:
        raise ValueError("Code must be provided to construct the command.")
    code = args.code
    if len(code) >= 2 and code[0] == code[-1] and code[0] in ("'", '"'):
        code = code[1:-1]

    return [
        "/opt/google/chrome-remote-desktop/start-host",
        f"--code={code}",
        f"--redirect-url={redirect_url}",
        f"--name={name}",
    ]


def reconstruct_command(command: str) -> list[str]:
    """Parse the allocator-supplied CRD command and return a safe argv."""
    arg_to_parse = command.split()

    parser = create_parser()
    args, _ = parser.parse_known_args(args=arg_to_parse)

    return construct_command(args)


def connect_to_crd(command, pin):
    argv = reconstruct_command(command)

    # input the pin code with verification
    input_pin = pin + "\n"
    input_pin_verification = input_pin + input_pin

    # Populate USER/LOGNAME/HOME from the current uid so start-host's
    # username lookup matches getpwuid(). With shell=True this was
    # normalized implicitly by /bin/sh; under execve we must pass it
    # ourselves or start-host aborts (SIGTRAP) on the mismatch.
    pw = pwd.getpwuid(os.getuid())
    env = {
        **os.environ,
        "DISPLAY": "",
        "USER": pw.pw_name,
        "LOGNAME": pw.pw_name,
        "HOME": pw.pw_dir,
    }

    result = subprocess.run(
        argv,
        input=input_pin_verification,
        shell=False,
        capture_output=True,
        text=True,
        env=env,
    )

    # start-host writes the host config to ~/.config/chrome-remote-desktop/
    # BEFORE it tries to launch the daemon via systemctl. In Docker there
    # is no systemd running, so the systemctl call fails and start-host
    # reports a non-zero exit — but the registration itself succeeded.
    # If the host config is present, start the daemon directly via
    # chrome-remote-desktop --start, bypassing systemd entirely.
    if is_crd_registered():
        logger.info(
            "CRD host registered (start-host exit=%d); "
            "starting daemon via chrome-remote-desktop --start.",
            result.returncode,
        )
        start_crd_daemon()
    elif result.returncode == 0:
        logger.info("CRD connection established successfully")
    else:
        logger.error(
            "CRD connection failed (exit %d): %s",
            result.returncode,
            result.stderr.strip(),
        )


def is_crd_registered() -> bool:
    """Return True if CRD has already been registered on this container."""
    return bool(glob.glob(CRD_HOST_CONFIG_GLOB))


def start_crd_daemon() -> None:
    """Start the CRD daemon from an existing host registration.

    Runs the same command systemd's ``chrome-remote-desktop@<user>``
    unit would invoke (``/opt/google/chrome-remote-desktop/chrome-remote-desktop
    --start --new-session``), bypassing systemd entirely. Used both on
    warm container restarts (where start-host would fail because the
    auth code is already consumed) and on first boot after start-host
    registers the host but cannot launch the daemon because systemctl
    is not available in the container.
    """
    if not is_crd_registered():
        logger.error("No CRD host config found; cannot start daemon")
        return
    command = (
        "/opt/google/chrome-remote-desktop/chrome-remote-desktop "
        "--start --new-session"
    )
    env = {
        **os.environ,
        "XDG_SESSION_CLASS": "user",
        "XDG_SESSION_TYPE": "x11",
    }
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
    except subprocess.TimeoutExpired:
        logger.error(
            "Timed out waiting for CRD daemon to start; subscribe "
            "will retry on the next NOTIFY"
        )
        return
    if result.returncode == 0:
        logger.info("CRD daemon started")
    else:
        logger.error(
            f"Failed to start CRD daemon: {result.stderr.strip()}"
        )
