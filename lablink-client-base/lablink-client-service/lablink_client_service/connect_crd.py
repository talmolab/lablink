import argparse
import subprocess


def create_parser():
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


def construct_command(args):
    """Constructs the Linux CRD command to connect to a remote machine.

    Args:
        args (argparse.Namespace): The command line arguments.

    Returns:
        str: The Linux CRD command to connect to a remote machine.
    """

    redirect_url = "'https://remotedesktop.google.com/_/oauthredirect'"
    name = "$(hostname)"

    command = "DISPLAY= /opt/google/chrome-remote-desktop/start-host"
    command += f" --code={args.code}"
    command += f" --redirect-url={redirect_url}"
    command += f" --name={name}"

    return command


def reconstruct_command(command: str = None):
    """Reconstructs the Chrome Remote Desktop command.

    Args:
        command (str, optional): CRD command to connect to the machine. Defaults to None.

    Returns:
        str: Reconstructed command to connect to the machine.
    """
    if command is None:
        arg_to_parse = None
    else:
        arg_to_parse = command.split()

    # Parse the command line arguments
    parser = create_parser()
    args, _ = parser.parse_known_args(args=arg_to_parse)

    print(vars(args))

    # Construct the command to be executed
    command = construct_command(args)
    print(f"Command to be executed: {command}")

    return command


def connect_to_crd(command=None, pin=None):
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

    # Check the result
    print(f"Output:\n {result.stdout}")

    if result.stderr:
        print(f"Error: {result.stderr}")
