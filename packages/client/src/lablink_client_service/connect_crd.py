import argparse
import glob
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


def construct_command(args) -> str:
    """Constructs the Linux CRD command to connect to a remote machine.

    Args:
        args (argparse.Namespace): The command line arguments.

    Returns:
        str: The Linux CRD command to connect to a remote machine.
    """

    redirect_url = "'https://remotedesktop.google.com/_/oauthredirect'"
    name = os.getenv("VM_NAME", "$(hostname)")

    if args.code is None:
        raise ValueError("Code must be provided to construct the command.")

    command = "DISPLAY= /opt/google/chrome-remote-desktop/start-host"
    command += f" --code={args.code}"
    command += f" --redirect-url={redirect_url}"
    command += f" --name={name}"

    return command


def reconstruct_command(command: str) -> str:
    """Reconstructs the Chrome Remote Desktop command.

    Args:
        command (str): CRD command to connect to the machine.

    Returns:
        str: Reconstructed command to connect to the machine.
    """
    arg_to_parse = command.split()

    # Parse the command line arguments
    parser = create_parser()
    args, _ = parser.parse_known_args(args=arg_to_parse)

    # Construct the command to be executed
    command = construct_command(args)

    return command


def connect_to_crd(command, pin):
    # Parse the command line arguments
    command = reconstruct_command(command)

    # input the pin code with verification
    input_pin = pin + "\n"
    input_pin_verification = input_pin + input_pin

    # Execute the command
    result = subprocess.run(
        command,
        input=input_pin_verification,
        shell=True,
        capture_output=True,
        text=True,
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
