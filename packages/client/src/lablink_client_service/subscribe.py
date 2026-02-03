import requests
import os
import time
import random

import hydra
import logging

from lablink_client_service.conf.structured_config import Config
from lablink_client_service.connect_crd import connect_to_crd, set_logger
from lablink_client_service.logger_utils import CloudAndConsoleLogger

logger = logging.getLogger(__name__)
MAX_RETRIES = None  # No limit on retries
RETRY_DELAY = 10


def subscribe(cfg: Config) -> None:
    global logger
    logger = CloudAndConsoleLogger(module_name="subscribe")
    set_logger(logger)  # Set the logger for connect_crd

    logger.info("Starting LabLink client service")

    # Define the URL for the POST request
    # Use ALLOCATOR_URL env var if set (supports HTTPS),
    # otherwise use host:port with HTTP
    allocator_url = os.getenv("ALLOCATOR_URL")
    if allocator_url:
        base_url = allocator_url.rstrip("/")
    else:
        base_url = f"http://{cfg.allocator.host}:{cfg.allocator.port}"

    # Sanitize URL to remove prepended dots
    # Handles cases like:
    # - http://.lablink.sleap.ai -> http://lablink.sleap.ai
    # - https://.lablink.sleap.ai -> https://lablink.sleap.ai
    # - .lablink.sleap.ai -> lablink.sleap.ai
    base_url = base_url.replace("://.", "://")
    if base_url.startswith("."):
        base_url = base_url[1:]

    url = f"{base_url}/vm_startup"

    # Define hostname for the client
    hostname = os.getenv("VM_NAME")
    logger.info(f"Connecting to allocator as '{hostname}'")

    # Retry loop: Keep trying to connect until successful or VM is terminated
    # This ensures the VM can connect to CRD even if there are transient network issues
    retry_count = 0

    while True:
        if retry_count > 0:
            logger.info(
                f"Retrying connection to allocator in {RETRY_DELAY} seconds... "
                f"(Attempt {retry_count + 1})"
            )
            jitter = random.uniform(0, 5)
            time.sleep(RETRY_DELAY + jitter)

        try:
            # Send a POST request to the specified URL
            # Note: This endpoint blocks until a user assigns a CRD command,
            # so we use a very long timeout.
            # The allocator uses PostgreSQL LISTEN/NOTIFY to wait for VM
            # assignment. Timeout tuple: (connect, read) = (30s, 7 days)
            response = requests.post(
                url, json={"hostname": hostname}, timeout=(30, 604800)
            )

            # Check if the request was successful
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "success":
                    logger.info("Received CRD command from allocator")
                    command = data["command"]
                    pin = data["pin"]

                    # Execute the command
                    connect_to_crd(pin=pin, command=command)
                    logger.info("CRD setup complete")
                    break  # Success - exit retry loop
                else:
                    logger.error(f"Allocator rejected request: {data.get('message')}")
                    break  # Server explicitly rejected - don't retry
            else:
                logger.warning(
                    f"Allocator returned status {response.status_code}, retrying..."
                )
                # Will retry after delay

        except requests.exceptions.Timeout:
            logger.warning("Request to allocator timed out, retrying...")
            # Will retry after delay

        except requests.exceptions.RequestException as e:
            logger.warning(f"Request to allocator failed: {e}, retrying...")
            # Will retry after delay

        # Increment retry count
        retry_count += 1


@hydra.main(version_base=None, config_name="config")
def main(cfg: Config) -> None:
    subscribe(cfg)


if __name__ == "__main__":
    main()
