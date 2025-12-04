import time
import logging
import requests
import os
import random

import psutil
import hydra

from lablink_client_service.conf.structured_config import Config
from lablink_client_service.logger_utils import CloudAndConsoleLogger

# Default logger setup
logger = logging.getLogger(__name__)

MAX_API_RETRIES = 5
API_RETRY_DELAY = 10  # seconds


def is_process_running(process_name: str) -> bool:
    """
    Check if a specific process is running.
    """
    for proc in psutil.process_iter():
        try:
            if any(process_name in part for part in proc.cmdline()):
                if "update_inuse_status" in " ".join(proc.cmdline()):
                    logger.debug(
                        f"Skipping process '{process_name}' as it is the current script"
                    )
                    continue
                logger.debug(f"Found process: {proc.cmdline()}")
                logger.debug(f"Process '{process_name}' is running.")
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    logger.debug(f"Process '{process_name}' is not running.")
    return False


def default_callback(process_name: str):
    """Default callback to log when a process is detected."""
    logger.info(f"Process '{process_name}' started.")


def listen_for_process(
    process_name: str, interval: int = 20, callback_func=None
) -> None:
    """Listen for a specific process to start or stop.

    Args:
        process_name (str): The name of the process to listen for.
        interval (int, optional): The interval (in seconds) to check the process status.
        callback_func (callable, optional): A callback function to execute when the
            process state changes.
    """

    # Set up a default callback function if none is provided
    if callback_func is None:
        callback_func = lambda: default_callback(process_name)

    logger.debug(f"Listening for process '{process_name}' every {interval} seconds.")

    # Continuously check if the process is running
    process_running_prev = is_process_running(process_name)
    while True:
        # Check if the process is running now
        process_running_curr = is_process_running(process_name)

        # Compare the current state with the previous state
        if process_running_prev != process_running_curr:
            if callback_func:
                logger.info(f"Process '{process_name}' state changed.")
                callback_func()

        # Update the previous state
        process_running_prev = process_running_curr

        # Wait for the specified interval before checking again
        jitter = random.uniform(0, 5)
        time.sleep(interval + jitter)


def call_api(process_name, url):
    logger.debug(f"Calling API for process: {process_name}")
    hostname = os.getenv("VM_NAME")
    status = is_process_running(process_name=process_name)

    retry_count = 0

    while retry_count < MAX_API_RETRIES:
        try:
            response = requests.post(
                url,
                json={"hostname": hostname, "status": status},
                # (connect_timeout, read_timeout): 10s to connect, 20s to read
                timeout=(10, 20),
            )
            response.raise_for_status()
            logger.debug(f"API call successful: {response.json()}")
            logger.info(
                f"Successfully updated in-use status for {process_name} to {status}"
            )
            break  # Success, exit retry loop
        except requests.exceptions.Timeout:
            logger.error(
                f"Status update timed out after 30 seconds "
                f"(Attempt {retry_count + 1}/{MAX_API_RETRIES}). Retrying..."
            )
        except requests.RequestException as e:
            logger.error(
                f"API call failed: {e} "
                f"(Attempt {retry_count + 1}/{MAX_API_RETRIES}). Retrying..."
            )

        retry_count += 1
        if retry_count < MAX_API_RETRIES:
            jitter = random.uniform(0, 5)
            time.sleep(API_RETRY_DELAY + jitter)
    else:
        logger.error(
            f"Failed to update in-use status after {MAX_API_RETRIES} attempts. "
            "Allocator might be unreachable."
        )


def api_callback(process_name: str, url: str):
    """Callback to call the API when process state changes."""
    call_api(process_name, url)


@hydra.main(version_base=None, config_path="conf", config_name="config")
def main(cfg: Config) -> None:
    # Configure the logger
    global logger
    logger = CloudAndConsoleLogger(module_name="update_inuse_status")
    logger.debug("Starting the update_inuse_status service...")

    # Define the URL for the POST request
    # Use ALLOCATOR_URL env var if set (supports HTTPS),
    # otherwise use host:port with HTTP
    allocator_url = os.getenv("ALLOCATOR_URL")
    if allocator_url:
        base_url = allocator_url.rstrip("/")
    else:
        base_url = f"http://{cfg.allocator.host}:{cfg.allocator.port}"
    url = f"{base_url}/api/update_inuse_status"

    url = url.replace("://.", "://")

    # Start listening for the process
    listen_for_process(
        process_name=cfg.client.software,
        interval=20,
        callback_func=lambda: api_callback(cfg.client.software, url),
    )


if __name__ == "__main__":
    main()
