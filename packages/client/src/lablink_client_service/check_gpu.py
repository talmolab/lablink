import subprocess
import time
import logging
import os
import random

import requests
import hydra

from lablink_client_service.conf.structured_config import Config
from lablink_client_service.logger_utils import CloudAndConsoleLogger


logger = logging.getLogger(__name__)


def check_gpu_health(allocator_url: str, interval: int = 20):
    """Check the health of the GPU.

    Args:
        allocator_url (str): The base URL of the allocator service.
        interval (int, optional): The interval in seconds to check the GPU health.
    """
    logger.debug("Starting GPU health check...")
    last_status = None
    base_url = allocator_url.rstrip("/")
    base_url = base_url.replace("://.", "://")

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
            logger.info(
                f"GPU health status changed: {curr_status}. Reporting to allocator."
            )

            report_retry_count = 0
            MAX_REPORT_RETRIES = 5
            REPORT_RETRY_DELAY = 10  # seconds

            while report_retry_count < MAX_REPORT_RETRIES:
                try:
                    response = requests.post(
                        f"{base_url}/api/gpu_health",
                        json={
                            "hostname": os.getenv("VM_NAME"),
                            "gpu_status": curr_status,
                        },
                        # (connect_timeout, read_timeout): 10s to connect, 20s to read
                        timeout=(10, 20),
                    )
                    response.raise_for_status()
                    logger.info(
                        f"Successfully reported GPU health status: {curr_status}"
                    )
                    last_status = curr_status
                    break  # Break out of the report retry loop on success
                except requests.exceptions.Timeout:
                    logger.error(
                        f"GPU health report timed out "
                        f"(Attempt {report_retry_count + 1}/{MAX_REPORT_RETRIES}). "
                        f"Retrying..."
                    )
                except requests.exceptions.RequestException as e:
                    logger.error(
                        f"Failed to report GPU health: {e} "
                        f"(Attempt {report_retry_count + 1}/{MAX_REPORT_RETRIES}). "
                        f"Retrying..."
                    )
                except Exception as e:
                    logger.error(
                        f"An unexpected error occurred while reporting GPU health: {e} "
                        f"(Attempt {report_retry_count + 1}/{MAX_REPORT_RETRIES}). "
                        f"Retrying..."
                    )

                report_retry_count += 1
                if report_retry_count < MAX_REPORT_RETRIES:
                    jitter = random.uniform(0, 5)
                    time.sleep(REPORT_RETRY_DELAY + jitter)
            else:
                logger.error(
                    f"Failed to report GPU health status after {MAX_REPORT_RETRIES} "
                    f"attempts. Allocator might be unreachable or experiencing issues."
                )
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
    # Use ALLOCATOR_URL env var if set (supports HTTPS),
    # otherwise use host:port with HTTP
    allocator_url_env = os.getenv("ALLOCATOR_URL")
    if allocator_url_env:
        allocator_url = allocator_url_env
    else:
        allocator_url = f"http://{cfg.allocator.host}:{cfg.allocator.port}"

    allocator_url = allocator_url.replace("://.", "://")

    check_gpu_health(allocator_url=allocator_url)


if __name__ == "__main__":
    main()
