import os
import subprocess
import json
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def get_instance_ips(terraform_dir: str) -> list:
    """Get the public IP addresses of the instances created by Terraform.
    Args:
        terraform_dir (str): The directory where the Terraform configuration is located.
    Raises:
        RuntimeError: Error running terraform output command.
        RuntimeError: Error decoding JSON output.
        ValueError: Expected output to be a list of IP addresses.
    Returns:
        list: A list of public IP addresses of the instances.
    """
    terraform_dir = Path(terraform_dir)
    try:
        result = subprocess.run(
            ["terraform", "output", "-json", "vm_public_ips"],
            cwd=terraform_dir,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error running terraform output: {e.stderr}")
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Error decoding JSON output: {e}")
    if not isinstance(output, list):
        raise ValueError("Expected output to be a list of IP addresses")
    return output


def get_ssh_private_key(terraform_dir: str) -> str:
    """Get the SSH private key used for connecting to the instances.
    Args:
        terraform_dir (str): The directory where the Terraform configuration is located.
    Raises:
        RuntimeError: Error running terraform output command.
    Returns:
        str: The path to the SSH private key file.
    """
    terraform_dir = Path(terraform_dir)
    try:
        result = subprocess.run(
            ["terraform", "output", "-raw", "lablink_private_key_pem"],
            cwd=terraform_dir,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error running terraform output: {e.stderr}")
    key_path = "/tmp/lablink_key.pem"
    with open(key_path, "w") as f:
        f.write(result.stdout)
    os.chmod(key_path, 0o400)
    return key_path


def get_instance_ids(terraform_dir: str) -> list:
    """Get the instance IDs of the instances created by Terraform.
    Args:
        terraform_dir (str): The directory where the Terraform configuration is located.
    Raises:
        RuntimeError: Error running terraform output command.
        RuntimeError: Error decoding JSON output.
        ValueError: Expected output to be a list of instance IDs.
    Returns:
        list: A list of instance IDs of the instances.
    """
    terraform_dir = Path(terraform_dir)
    try:
        result = subprocess.run(
            ["terraform", "output", "-json", "vm_instance_ids"],
            cwd=terraform_dir,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error running terraform output: {e.stderr}")
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Error decoding JSON output: {e}")
    if not isinstance(output, list):
        raise ValueError("Expected output to be a list of instance IDs")
    return output


def get_instance_names(terraform_dir: str) -> list:
    """Get the names of the instances created by Terraform.
    Args:
        terraform_dir (str): The directory where the Terraform configuration is located.
    Raises:
        RuntimeError: Error running terraform output command.
        RuntimeError: Error decoding JSON output.
        ValueError: Expected output to be a list of instance names.
    Returns:
        list: A list of names assigned to the EC2 instances.
    """
    terraform_dir = Path(terraform_dir)
    try:
        result = subprocess.run(
            ["terraform", "output", "-json", "vm_instance_names"],
            cwd=terraform_dir,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error running terraform output: {e.stderr}")
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Error decoding JSON output: {e}")
    if not isinstance(output, list):
        raise ValueError("Expected output to be a list of instance names")
    return output


def get_instance_timings(terraform_dir: str) -> dict:
    """Get the launch times of the instances created by Terraform.
    Args:
        terraform_dir (str): The directory where the Terraform configuration is located.
    Raises:
        RuntimeError: Error running terraform output command.
        RuntimeError: Error decoding JSON output.
        ValueError: Expected output to be a dictionary of launch times.
    Returns:
        dict: A dictionary mapping instance names to their launch times.
    """
    terraform_dir = Path(terraform_dir)
    try:
        result = subprocess.run(
            ["terraform", "output", "-json", "instance_terraform_apply_times"],
            cwd=terraform_dir,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Error running terraform output: {e.stderr}")
    try:
        timing_data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Error decoding JSON output: {e}")
    if not isinstance(timing_data, dict):
        raise ValueError("Expected output to be a dictionary.")

    return timing_data
