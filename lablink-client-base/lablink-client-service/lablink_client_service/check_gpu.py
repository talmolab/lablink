import subprocess
import time
import logging
import os

import requests
import hydra

from lablink_client_service.conf.structured_config import Config
from lablink_client_service.logger_config import setup_logger

# Set up logging
logger = setup_logger()


def check_gpu_health(allocator_ip: str, allocator_port: int, interval: int = 20):
    """Check the health of the GPU.

    Args:
        allocator_ip (str): The IP address of the allocator service.
        allocator_port (int): The port of the allocator service.
        interval (int, optional): The interval in seconds to check the GPU health. Defaults to 20.
    """
    logger.debug("Starting GPU health check...")
    while True:
        try:
            # Run the nvidia-smi command to check GPU health
            result = subprocess.run(
                ["nvidia-smi"],
                capture_output=True,
                text=True,
                check=True,
            )
            logger.info(f"GPU Health Check: {result.stdout.strip()}")
            requests.post(
                f"http://{allocator_ip}:{allocator_port}/api/gpu_health",
                json={
                    "hostname": os.getenv("VM_NAME"),
                    "gpu_status": "Healthy",
                    "message": result.stdout.strip(),
                },
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to check GPU health: {e}")
            # Command not found -> likely nvidia-smi is not installed
            if e.returncode == 127:
                logger.error(
                    "nvidia-smi command not found. Ensure NVIDIA drivers are installed."
                )
                requests.post(
                    f"http://{allocator_ip}:{allocator_port}/api/gpu_health",
                    json={
                        "hostname": os.getenv("VM_NAME"),
                        "gpu_status": "N/A",
                        "message": "nvidia-smi command not found",
                    },
                )
                # Terminate the loop if nvidia-smi is not available
                break
            else:
                logger.error(
                    f"nvidia-smi command failed with error: {e.stderr.strip()}"
                )
                requests.post(
                    f"http://{allocator_ip}:{allocator_port}/api/gpu_health",
                    json={
                        "hostname": os.environ["VM_NAME"],
                        "gpu_status": "Unhealthy",
                        "message": str(e),
                    },
                )
        except FileNotFoundError as e:
            logger.error(f"File not found: {e}")
            requests.post(
                f"http://{allocator_ip}:{allocator_port}/api/gpu_health",
                json={
                    "hostname": os.getenv("VM_NAME"),
                    "gpu_status": "N/A",
                    "message": "nvidia-smi command not found",
                },
            )
            break
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
        time.sleep(interval)


@hydra.main(version_base=None, config_name="config")
def main(cfg: Config) -> None:
    check_gpu_health(
        allocator_ip=cfg.allocator.host,
        allocator_port=cfg.allocator.port,
    )


if __name__ == "__main__":
    main()
