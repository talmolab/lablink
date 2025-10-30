import logging
import sys
from lablink_client_service.logger_config import setup_logger

def test_setup_logger_basic():
    """Test basic logger setup."""
    logger = setup_logger("test_logger_1")
    assert isinstance(logger, logging.Logger)
    assert logger.level == logging.DEBUG
    assert len(logger.handlers) == 1

def test_setup_logger_singleton():
    """Test that logger is a singleton and handlers are not duplicated."""
    logger1 = setup_logger("test_logger_2")
    assert len(logger1.handlers) == 1
    logger2 = setup_logger("test_logger_2")
    assert logger1 is logger2
    assert len(logger2.handlers) == 1, "Handlers should not be added more than once"

def test_setup_logger_handler_and_formatter():
    """Test the handler and formatter configuration."""
    logger = setup_logger("test_logger_3", level=logging.INFO)
    assert logger.level == logging.INFO
    assert len(logger.handlers) == 1
    handler = logger.handlers[0]
    assert isinstance(handler, logging.StreamHandler)
    assert handler.stream == sys.stdout
    formatter = handler.formatter
    assert isinstance(formatter, logging.Formatter)
    expected_format = "%(asctime)s %(name)s [%(levelname)s]: %(message)s"
    assert formatter._fmt == expected_format

def test_setup_logger_custom_name_and_level():
    """Test logger with a custom name and level."""
    custom_name = "my_custom_logger"
    custom_level = logging.WARNING
    logger = setup_logger(name=custom_name, level=custom_level)
    assert logger.name == custom_name
    assert logger.level == custom_level
    # Clean up handlers to avoid side effects in other tests if run in same process
    logger.handlers.clear()
