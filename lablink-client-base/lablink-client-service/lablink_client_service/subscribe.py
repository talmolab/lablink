from lablink_client_service.database import PostgresqlDatabase
import socket
import os
import hydra
from omegaconf import DictConfig, OmegaConf
import logging
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
    database = PostgresqlDatabase(
        dbname=cfg.db.dbname,
        user=cfg.db.user,
        password=cfg.db.password,
        host=cfg.db.host,
        port=cfg.db.port,
        table_name=cfg.db.table_name,
    )

    # Insert the hostname to the database
    database.insert_vm(hostname=socket.gethostname())

    # Listen to the message and send back if message is received
    # When a message is received, the callback function will be called (connect to CRD)
    channel = "vm_updates"
    database.listen_for_notifications(channel)


if __name__ == "__main__":
    main()
