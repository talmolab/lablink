import subprocess
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def find_slp_files_in_container(ip: str, key_path: str) -> list[str]:
    """SSH into the EC2 VM and find all .slp files in the running Docker container.
    Args:
        ip (str): The public IP address of the EC2 instance.
        key_path (str): The path to the SSH private key file.
    Returns:
        list[str]: A list of paths to .slp files found in the container.
    """
    cmd = (
        "cid=$(sudo docker ps -q | head -n1) && "
        "sudo docker exec $cid find /home/client/Desktop -name '*.slp' "
        "-not -path '*/models/*' -not -path '*/predictions/*'"
    )
    ssh_cmd = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-i",
        key_path,
        f"ubuntu@{ip}",
        cmd,
    ]

    try:
        result = subprocess.run(ssh_cmd, check=True, capture_output=True, text=True)
        files = result.stdout.strip().split("\n")
        return [f for f in files if f.strip()]
    except subprocess.CalledProcessError as e:
        logging.error(f"Error finding .slp files in container on {ip}: {e}")
        return []


def extract_slp_from_docker(ip: str, key_path: str, slp_files: list[str]) -> None:
    """
    SSH into the EC2 VM and extract .slp files from the running container to the EC2
    host file system under /home/ubuntu/slp_files.
    Args:
        ip (str): The public IP address of the EC2 instance.
        key_path (str): The path to the SSH private key file.
        slp_files (list[str]): A list of .slp file paths to extract from the container.
    Raises:
        subprocess.CalledProcessError: If the SSH command fails.
    """
    for file in slp_files:
        rel_path = file.replace("/home/client/Desktop/", "")
        dest_path = f"/home/ubuntu/slp_files/{rel_path}"
        dest_dir = Path(dest_path).parent
        cmd = (
            "cid=$(sudo docker ps -q | head -n1) && "
            f"mkdir -p {dest_dir} && "
            f"sudo docker cp $cid:'{file}' '{dest_path}'"
        )
        ssh_cmd = [
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-i",
            key_path,
            f"ubuntu@{ip}",
            cmd,
        ]

        try:
            subprocess.run(ssh_cmd, check=True)
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to copy {file} from container on {ip}: {e}")


def has_slp_files(ip: str, key_path: str) -> bool:
    """Check if the target VM has .slp files in /home/ubuntu/slp_files.
    Args:
        ip (str): The public IP address of the EC2 instance.
        key_path (str): The path to the SSH private key file.
    """
    ssh_cmd = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-i",
        key_path,
        f"ubuntu@{ip}",
        "sh -c 'ls /home/ubuntu/slp_files/*.slp 1>/dev/null 2>/dev/null && echo exists "
        "|| echo missing'",
    ]
    result = subprocess.run(ssh_cmd, capture_output=True, text=True)
    return result.stdout.strip() == "exists"


def rsync_slp_files_to_allocator(ip: str, key_path: str, local_dir: str) -> None:
    """Copy .slp files from the target VM's file system to the allocator's docker
    container.

    Args:
        ip (str): The public IP address of the EC2 instance.
        key_path (str): The path to the SSH private key file.
        local_dir (str): The local directory where the .slp files will be copied.
    """
    logger.debug(f"Copying the .slp files from VM {ip} to allocator...")
    cmd = [
        "rsync",
        "-avz",
        "--include",
        "**/",
        "--include",
        "**.slp",
        "--exclude",
        "*",
        "-e",
        f"ssh -o StrictHostKeyChecking=no -i {key_path}",
        f"ubuntu@{ip}:/home/ubuntu/slp_files/",
        f"{local_dir}/",
    ]

    if has_slp_files(ip, key_path):
        logger.debug(f"Copying .slp files from {ip} to {local_dir}")
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"Rsync stdout:\n{result.stdout}")
            logger.debug(f"Data downloaded to {local_dir}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error copying .slp files from {ip}: {e}")
            logger.error("Rsync stderr:\n" + e.stderr)
            raise
    else:
        logger.info(f"No .slp files found on VM {ip}. Skipping...")
