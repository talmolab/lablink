import socket
import hydra
from omegaconf import OmegaConf
import logging
import requests
from lablink_client_service.conf.structured_config import Config
from lablink_client_service.connect_crd import connect_to_crd

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s: %(message)s",
    datefmt="%H:%M",
)

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

url = "http://localhost:5000/vm_startup"

@hydra.main(version_base=None, config_name="config")
def main(cfg: Config) -> None:
    logger.debug("Starting the lablink client service...")
    logger.debug(f"Configuration: {OmegaConf.to_yaml(cfg)}")

    # Define hostname for the client
    hostname = socket.gethostname()
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


if __name__ == "__main__":
    main()
