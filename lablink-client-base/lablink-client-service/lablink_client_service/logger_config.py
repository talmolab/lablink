import logging
import sys
from typing import Optional

from lablink_client_service.conf.structured_config import Config
import watchtower
import boto3


def setup_logger(
    name: str = __name__,
    level=logging.DEBUG,
    config: Optional[Config] = None,
) -> logging.Logger:
    logger = logging.getLogger(name)

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

        # If using AWS CloudWatch, add watchtower handler
        cw_log_group = config.logging.group_name or "lablink_client_logger"
        cw_log_stream = config.logging.stream_name or "${oc.env:VM_NAME,default}"
        boto3_session = boto3.Session()
        cw_handler = watchtower.CloudWatchLogHandler(
            boto3_session=boto3_session,
            log_group=cw_log_group,
            stream_name=cw_log_stream,
        )
        cw_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(cw_handler)

    return logger
