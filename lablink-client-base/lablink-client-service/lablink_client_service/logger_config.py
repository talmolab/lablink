import logging
import sys
from typing import Optional
import os

from lablink_client_service.conf.structured_config import Config
import watchtower
import boto3


def setup_logger(
    name: str = __name__,
    level=logging.DEBUG,
    config: Optional[Config] = None,
) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Always clear old handlers
    for h in logger.handlers:
        logger.removeHandler(h)

    # Prevent adding multiple handlers if already set
    if not logger.hasHandlers():
        # Console handler
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s %(name)s [%(levelname)s]: %(message)s", "%H:%M"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(level)

        if config and hasattr(config, "logging"):
            try:
                hostname = os.environ.get("VM_NAME", "default")
                # If using structured config, set up logging based on config
                group_name = getattr(
                    config.logging, "group_name", "lablink_client_logger"
                )
                stream_name = getattr(config.logging, "stream_name", hostname)
                logger.debug(
                    f"Using CloudWatch group: {group_name}, stream: {stream_name}"
                )
                session = boto3.Session()
                cw_handler = watchtower.CloudWatchLogHandler(
                    log_group=group_name,
                    stream_name=stream_name,
                    create_log_group=True,
                    boto3_session=session,
                )
                cw_handler.setFormatter(
                    logging.Formatter(
                        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                    )
                )
                logger.addHandler(cw_handler)
                logger.info(
                    f"CloudWatch logging enabled for group '{group_name}' and stream '{stream_name}'"
                )
            except Exception as e:
                logger.error(f"Failed to set up CloudWatch logging: {e}")
                logger.info("Continuing without CloudWatch logging.")

    return logger


def setup_logger_from_hydra(cfg: Config, name: str = __name__) -> logging.Logger:
    """Convenience function to setup logger directly from Hydra config."""
    return setup_logger(name=name, config=cfg)
