
from unittest.mock import MagicMock

import pytest
from lablink_client_service.logger_utils import CloudAndConsoleLogger


@pytest.fixture
def logger_instance():
    """Fixture to create a CloudAndConsoleLogger instance."""
    return CloudAndConsoleLogger(
        module_name="test_module",
    )


def test_logger_initialization(logger_instance):
    """Test that the logger and its components are initialized correctly."""
    assert logger_instance.name == "test_module"
    assert logger_instance.console_logger is not None


def test_logging_methods(logger_instance):
    """Test that logging methods are passed to the console logger."""
    logger_instance.console_logger = MagicMock()

    logger_instance.debug("This is a debug message")
    logger_instance.console_logger.debug.assert_called_once_with(
        "This is a debug message"
    )

    logger_instance.info("This is an info message")
    logger_instance.console_logger.info.assert_called_once_with(
        "This is an info message"
    )


def test_pprint_method(logger_instance):
    """Test the pprint method to ensure it logs formatted output."""
    logger_instance.console_logger = MagicMock()

    test_obj = {"key": "value", "nested": {"a": 1}}
    logger_instance.pprint(test_obj)

    # Check that the console logger was called with the pretty-printed string
    logger_instance.console_logger.log.assert_called_once()


def test_backwards_compatible_init():
    """Test that old-style init args (log_group, region) are accepted without error."""
    logger = CloudAndConsoleLogger(
        module_name="compat_test",
        log_group="some_group",
        region="us-east-1",
    )
    assert logger.name == "compat_test"
