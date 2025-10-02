import subprocess
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def find_files_in_container(ip: str, key_path: str, extension: str) -> list[str]:
    """SSH into the EC2 VM and find all files in the running Docker container.
    Args:
        ip (str): The public IP address of the EC2 instance.
        key_path (str): The path to the SSH private key file.
        extension (str): The file extension to search for.
    Returns:
        list[str]: A list of paths to files found in the container.
    """
    cmd = (
        "cid=$(sudo docker ps -q | head -n1) && "
        f"sudo docker exec $cid find /home/client/Desktop -name '*.{extension}' "
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
        logging.error(f"Error finding .{extension} files in container on {ip}: {e}")
        return []


def extract_files_from_docker(ip: str, key_path: str, files: list[str]) -> None:
    """
    SSH into the EC2 VM and extract files from the running container to the EC2
    host file system under /home/ubuntu/extracted_files.
    Args:
        ip (str): The public IP address of the EC2 instance.
        key_path (str): The path to the SSH private key file.
        files (list[str]): A list of file paths to extract from the container.
    Raises:
        subprocess.CalledProcessError: If the SSH command fails.
    """
    for file in files:
        rel_path = file.replace("/home/client/Desktop/", "")
        dest_path = f"/home/ubuntu/extracted_files/{rel_path}"
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


def has_files(ip: str, key_path: str, extension: str) -> bool:
    """Check if the target VM has specific files in /home/ubuntu/extracted_files.
    Args:
        ip (str): The public IP address of the EC2 instance.
        key_path (str): The path to the SSH private key file.
        extension (str): The file extension to check for.
    """
    ssh_cmd = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=no",
        "-i",
        key_path,
        f"ubuntu@{ip}",
        f"sh -c 'ls /home/ubuntu/extracted_files/*.{extension} 1>/dev/null 2>/dev/null && echo exists "
        "|| echo missing'",
    ]
    result = subprocess.run(ssh_cmd, capture_output=True, text=True)
    return result.stdout.strip() == "exists"


def rsync_files_to_allocator(ip: str, key_path: str, local_dir: str, extension: str) -> None:
    """Copy specific files from the target VM's file system to the allocator's docker
    container.

    Args:
        ip (str): The public IP address of the EC2 instance.
        key_path (str): The path to the SSH private key file.
        extension (str): The file extension to copy.
        local_dir (str): The local directory where the .{extension} files will be copied.
    """
    logger.debug(f"Copying the .{extension} files from VM {ip} to allocator...")
    cmd = [
        "rsync",
        "-avz",
        "--include",
        "**/",
        "--include",
        f"**.{extension}",
        "--exclude",
        "*",
        "-e",
        f"ssh -o StrictHostKeyChecking=no -i {key_path}",
        f"ubuntu@{ip}:/home/ubuntu/extracted_files/",
        f"{local_dir}/",
    ]

    if has_files(ip, key_path, extension):
        logger.debug(f"Copying .{extension} files from {ip} to {local_dir}")
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"Rsync stdout:\n{result.stdout}")
            logger.debug(f"Data downloaded to {local_dir}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error copying .{extension} files from {ip}: {e}")
            logger.error("Rsync stderr:\n" + e.stderr)
            raise
    else:
        logger.info(f"No .{extension} files found on VM {ip}. Skipping...")
