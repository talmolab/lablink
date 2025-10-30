import logging
import sys


def setup_logger(
    name: str = "lablink_client_logger", level=logging.DEBUG
) -> logging.Logger:
    logger = logging.getLogger(name)

    # Ensure the logger's level is set
    logger.setLevel(level)

    # Prevent adding duplicate handlers
    if not any(
        isinstance(handler, logging.StreamHandler) and handler.stream == sys.stdout
        for handler in logger.handlers
    ):
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s %(name)s [%(levelname)s]: %(message)s", "%H:%M"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger
