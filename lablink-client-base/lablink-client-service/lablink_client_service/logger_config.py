# logger_config.py
import logging
import sys


def setup_logger(
    name: str = "lablink_client_logger", level=logging.DEBUG
) -> logging.Logger:
    logger = logging.getLogger(name)

    # Prevent adding multiple handlers if already set
    if not logger.hasHandlers():
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s %(name)s [%(levelname)s]: %(message)s", "%H:%M"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(level)

    return logger
