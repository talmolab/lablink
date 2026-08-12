import os
import subprocess
import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def get_ssh_private_key(tofu_dir: str) -> str:
    """Get the SSH private key used for connecting to the instances.
    Args:
        tofu_dir (str): The directory where the OpenTofu configuration is located.
    Raises:
        RuntimeError: Error running tofu output command.
    Returns:
        str: The path to the SSH private key file.
    """
    tofu_dir = Path(tofu_dir)
    try:
        result = subprocess.run(
            ["tofu", "output", "-raw", "lablink_private_key_pem"],
            cwd=tofu_dir,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error running tofu output: {e.stderr}")
    key_path = "/tmp/lablink_key.pem"
    with open(key_path, "w") as f:
        f.write(result.stdout)
    os.chmod(key_path, 0o400)
    return key_path


def get_instance_ids(tofu_dir: str) -> list:
    """Get the instance IDs of the instances created by OpenTofu.
    Args:
        tofu_dir (str): The directory where the OpenTofu configuration is located.
    Raises:
        RuntimeError: Error running tofu output command.
        RuntimeError: Error decoding JSON output.
        ValueError: Expected output to be a list of instance IDs.
    Returns:
        list: A list of instance IDs of the instances.
    """
    tofu_dir = Path(tofu_dir)
    try:
        result = subprocess.run(
            ["tofu", "output", "-json", "vm_instance_ids"],
            cwd=tofu_dir,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error running tofu output: {e.stderr}")
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Error decoding JSON output: {e}")
    if not isinstance(output, list):
        raise ValueError("Expected output to be a list of instance IDs")
    return output


def get_instance_names(tofu_dir: str) -> list:
    """Get the names of the instances created by OpenTofu.
    Args:
        tofu_dir (str): The directory where the OpenTofu configuration is located.
    Raises:
        RuntimeError: Error running tofu output command.
        RuntimeError: Error decoding JSON output.
        ValueError: Expected output to be a list of instance names.
    Returns:
        list: A list of names assigned to the EC2 instances.
    """
    tofu_dir = Path(tofu_dir)
    try:
        result = subprocess.run(
            ["tofu", "output", "-json", "vm_instance_names"],
            cwd=tofu_dir,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error running tofu output: {e.stderr}")
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Error decoding JSON output: {e}")
    if not isinstance(output, list):
        raise ValueError("Expected output to be a list of instance names")
    return output


def get_instance_timings(tofu_dir: str) -> dict:
    """Get the launch times of the instances created by OpenTofu.
    Args:
        tofu_dir (str): The directory where the OpenTofu configuration is located.
    Raises:
        RuntimeError: Error running tofu output command.
        RuntimeError: Error decoding JSON output.
        ValueError: Expected output to be a dictionary of launch times.
    Returns:
        dict: A dictionary mapping instance names to their launch times.
    """
    tofu_dir = Path(tofu_dir)
    try:
        result = subprocess.run(
            ["tofu", "output", "-json", "instance_terraform_apply_times"],
            cwd=tofu_dir,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error running tofu output: {e.stderr}")
    try:
        timing_data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Error decoding JSON output: {e}")
    if not isinstance(timing_data, dict):
        raise ValueError("Expected output to be a dictionary of launch times.")

    return timing_data
