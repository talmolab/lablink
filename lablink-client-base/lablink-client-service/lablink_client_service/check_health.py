import subprocess
import time
import logging

import requests
from omegaconf import OmegaConf
import hydra

from lablink_client_service.conf.structured_config import Config

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s: %(message)s",
    datefmt="%H:%M",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


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
                json={"status": "healthy", "message": result.stdout.strip()},
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
                        "status": "N/A",
                        "message": "nvidia-smi command not found",
                    },
                )
            else:
                logger.error(
                    f"nvidia-smi command failed with error: {e.stderr.strip()}"
                )
                requests.post(
                    f"http://{allocator_ip}:{allocator_port}/api/gpu_health",
                    json={"status": "Unhealthy", "message": str(e)},
                )
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}")
        time.sleep(interval)


@hydra.main(version_base=None, config_name="config")
def main(cfg: Config) -> None:
    check_gpu_health(
        allocator_ip=cfg.allocator.host,
        allocator_port=cfg.allocator.port,
        interval=60,
    )


if __name__ == "__main__":
    main()
