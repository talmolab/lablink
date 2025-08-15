import requests
import os

import hydra
from omegaconf import OmegaConf

from lablink_client_service.conf.structured_config import Config
from lablink_client_service.connect_crd import connect_to_crd, set_logger
from lablink_client_service.logger_utils import CloudAndConsoleLogger

logger = logging.getLogger(__name__)


def subscribe(cfg: Config) -> None:
    global logger
    logger = CloudAndConsoleLogger(module_name="subscribe")
    set_logger(logger)  # Set the logger for connect_crd

    logger.debug("Starting the lablink client service...")
    logger.debug(f"Configuration: {OmegaConf.to_yaml(cfg)}")

    # Define the URL for the POST request
    url = f"http://{cfg.allocator.host}:{cfg.allocator.port}/vm_startup"
    logger.debug(f"URL: {url}")

    # Define hostname for the client
    hostname = os.getenv("VM_NAME")
    logger.debug(f"Hostname: {hostname}")

    # Send a POST request to the specified URL
    response = requests.post(url, json={"hostname": hostname})

    # Check if the request was successful
    if response.status_code == 200:
        logger.debug("POST request was successful.")
        data = response.json()
        if data.get("status") == "success":
            logger.debug("Received success response from server.")
            command = data["command"]
            pin = data["pin"]
            logger.debug(f"Command received: {command}")
            logger.debug(f"Pin received: {pin}")

            # Execute the command
            connect_to_crd(pin=pin, command=command)
            logger.debug("Command executed successfully.")
        else:
            logger.error("Received error response from server.")
            logger.error(f"Error message: {data.get('message')}")
    else:
        logger.error(f"POST request failed with status code: {response.status_code}")


@hydra.main(version_base=None, config_name="config")
def main(cfg: Config) -> None:
    subscribe(cfg)


if __name__ == "__main__":
    main()
