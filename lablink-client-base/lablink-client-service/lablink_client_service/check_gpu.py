import subprocess
import time
import logging
import os

import requests
import hydra

from lablink_client_service.conf.structured_config import Config
from lablink_client_service.logger_utils import CloudAndConsoleLogger


logger = logging.getLogger(__name__)


def check_gpu_health(allocator_ip: str, allocator_port: int, interval: int = 20):
    """Check the health of the GPU.

    Args:
        allocator_ip (str): The IP address of the allocator service.
        allocator_port (int): The port of the allocator service.
        interval (int, optional): The interval in seconds to check the GPU health.
    """
    logger.debug("Starting GPU health check...")
    last_status = None

    while True:
        curr_status = None
        break_now = False

        try:
            # Run the nvidia-smi command to check GPU health
            result = subprocess.run(
                ["nvidia-smi"],
                capture_output=True,
                text=True,
                check=True,
            )
            curr_status = "Healthy"
            logger.info(f"GPU Health Check: {result.stdout.strip()}")

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to check GPU health: {e}")
            # Command not found -> likely nvidia-smi is not installed
            if e.returncode == 127:
                logger.error(
                    "nvidia-smi command not found. Ensure NVIDIA drivers are installed."
                )
                curr_status = "N/A"
                break_now = True

            else:
                logger.error(
                    f"nvidia-smi command failed with error: {e.stderr.strip()}"
                )
                curr_status = "Unhealthy"

        except FileNotFoundError as e:
            # This exception is raised if the nvidia-smi command is not found
            logger.error(f"File not found: {e}")
            curr_status = "N/A"
            break_now = True

        except Exception as e:
            curr_status = "Unhealthy"
            logger.error(f"An unexpected error occurred: {e}")

        if curr_status != last_status or break_now:
            logger.info(f"GPU health status changed: {curr_status}")
            try:
                requests.post(
                    f"http://{allocator_ip}:{allocator_port}/api/gpu_health",
                    json={
                        "hostname": os.getenv("VM_NAME"),
                        "gpu_status": curr_status,
                    },
                )
            except Exception as e:
                logger.error(f"Failed to report GPU health: {e}")
            last_status = curr_status

        if break_now:
            break
        time.sleep(interval)


@hydra.main(version_base=None, config_name="config")
def main(cfg: Config) -> None:
    global logger
    logger = CloudAndConsoleLogger(
        module_name="check_gpu",
    )
    # Check GPU health
    check_gpu_health(
        allocator_ip=cfg.allocator.host,
        allocator_port=cfg.allocator.port,
    )


if __name__ == "__main__":
    main()
