import os
import subprocess
import json
from pathlib import Path


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
    result = subprocess.run(
        ["terraform", "output", "-json", "vm_public_ips"],
        cwd=terraform_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Error running terraform output: {result.stderr}")
    try:
        output = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Error decoding JSON output: {e}")
    if not isinstance(output, list):
        raise ValueError("Expected output to be a list of IP addresses")
    return output


def get_ssh_key_pairs(terraform_dir: str) -> str:
    """Get the SSH private key used for connecting to the instances.

    Args:
        terraform_dir (str): The directory where the Terraform configuration is located.

    Raises:
        RuntimeError: Error running terraform output command.

    Returns:
        str: The path to the SSH private key file.
    """
    terraform_dir = Path(terraform_dir)
    result = subprocess.run(
        ["terraform", "output", "-raw", "lablink_private_key_pem"],
        cwd=terraform_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Error running terraform output: {result.stderr}")
    key_path = "/tmp/lablink_key.pem"
    with open(key_path, "w") as f:
        f.write(result.stdout)
    os.chmod(key_path, 0o400)
    return key_path
