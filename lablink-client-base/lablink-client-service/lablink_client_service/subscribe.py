from lablink_client_service.database import PostgresqlDatabase
import socket
import os
import hydra
from omegaconf import DictConfig, OmegaConf
import logging
import requests
from lablink_client_service.conf.structured_config import Config

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


@hydra.main(version_base=None, config_name="config")
def main(cfg: Config) -> None:
    logger.debug("Starting the lablink client service...")
    logger.debug(f"Configuration: {OmegaConf.to_yaml(cfg)}")

    # Connect to the PostgreSQL database
    # database = PostgresqlDatabase(
    #     dbname=cfg.db.dbname,
    #     user=cfg.db.user,
    #     password=cfg.db.password,
    #     host=cfg.db.host,
    #     port=cfg.db.port,
    #     table_name=cfg.db.table_name,
    # )

    # Insert the hostname to the database
    # database.insert_vm(hostname=socket.gethostname())

    # Listen to the message and send back if message is received
    # When a message is received, the callback function will be called (connect to CRD)
    # channel = "vm_updates"
    # database.listen_for_notifications(channel)

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
        else:
            logger.error("Received error response from server.")
            logger.error(f"Error message: {data.get('message')}")
    else:
        logger.error(f"POST request failed with status code: {response.status_code}")


if __name__ == "__main__":
    main()
