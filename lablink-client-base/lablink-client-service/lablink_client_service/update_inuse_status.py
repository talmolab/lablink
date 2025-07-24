import time
import logging
import requests
import os

import psutil
import hydra
from omegaconf import OmegaConf

from lablink_client_service.conf.structured_config import Config
from lablink_client_service.logger_config import setup_logger

# Set up logging
logger = setup_logger()


def is_process_running(process_name: str) -> bool:
    """
    Check if a specific process is running.
    """
    for proc in psutil.process_iter():
        try:
            if any(process_name in part for part in proc.cmdline()):
                if "update_inuse_status" in " ".join(proc.cmdline()):
                    logger.debug(
                        f"Skipping process '{process_name}' as it is the current script."
                    )
                    continue
                logger.debug(f"Found process: {proc.cmdline()}")
                logger.debug(f"Process '{process_name}' is running.")
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    logger.debug(f"Process '{process_name}' is not running.")
    return False


def listen_for_process(
    process_name: str, interval: int = 20, callback_func=None
) -> None:
    """
    Listen for a specific process to start or stop.

    Args:
        process_name (str): The name of the process to listen for.
        interval (int, optional): The interval (in seconds) to check the process status. Defaults to 20.
        callback_func (callable, optional): A callback function to execute when the process state changes.
    """

    # Set up a default callback function if none is provided
    if callback_func is None:
        callback_func = lambda: logger.info(f"Process '{process_name}' started.")

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
        time.sleep(interval)


def call_api(process_name, url):
    logger.debug(f"Calling API for process: {process_name}")
    hostname = os.getenv("VM_NAME")
    status = is_process_running(process_name=process_name)

    try:
        response = requests.post(
            url,
            json={"hostname": hostname, "status": status},
        )
        response.raise_for_status()
        logger.debug(f"API call successful: {response.json()}")
    except requests.RequestException as e:
        logger.error(f"API call failed: {e}")


@hydra.main(version_base=None, config_path="conf", config_name="config")
def main(cfg: Config) -> None:
    logger.debug("Starting the update_inuse_status service...")
    logger.debug(f"Configuration: {OmegaConf.to_yaml(cfg)}")

    # Define the URL for the POST request
    url = f"http://{cfg.allocator.host}:{cfg.allocator.port}/api/update_inuse_status"
    logger.debug(f"URL: {url}")

    # Start listening for the process
    listen_for_process(
        process_name=cfg.client.software,
        interval=20,
        callback_func=lambda: call_api(cfg.client.software, url),
    )


if __name__ == "__main__":
    main()
