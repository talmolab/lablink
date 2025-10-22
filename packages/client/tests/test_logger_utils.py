
import logging
import os
from unittest.mock import MagicMock, patch, call

import pytest
from lablink_client_service.logger_utils import CloudAndConsoleLogger


class ComparableMagicMock(MagicMock):
    """A MagicMock that can be compared to integers."""

    def __ge__(self, other):
        return True

    def __le__(self, other):
        return True


@pytest.fixture
def mock_boto3():
    """Fixture to mock boto3 and watchtower."""
    with patch("boto3.client") as mock_boto_client, patch(
        "watchtower.CloudWatchLogHandler"
    ) as mock_watchtower_handler_class: # Renamed to avoid confusion
        mock_boto_client.return_value = MagicMock()  # Keep boto3.client simple

        # Create a mock instance for CloudWatchLogHandler
        mock_handler_instance = MagicMock()
        # Ensure it has a level attribute that can be compared
        mock_handler_instance.level = logging.DEBUG # Set a default level
        mock_handler_instance.setFormatter = MagicMock() # Mock setFormatter
        mock_handler_instance.addHandler = MagicMock() # Mock addHandler

        mock_watchtower_handler_class.return_value = mock_handler_instance

        yield mock_boto_client, mock_watchtower_handler_class


@pytest.fixture
def logger_instance(mock_boto3):
    """Fixture to create a CloudAndConsoleLogger instance with mocks."""
    return CloudAndConsoleLogger(
        module_name="test_module",
        log_group="test_group",
        region="us-east-1",
    )


def test_logger_initialization(logger_instance, mock_boto3):
    """Test that the logger and its components are initialized correctly."""
    mock_boto_client, mock_watchtower_handler = mock_boto3

    assert logger_instance.name == "test_module"
    assert logger_instance.log_group == "test_group"
    assert logger_instance.region == "us-east-1"
    assert logger_instance.console_logger is not None
    assert logger_instance.cloud_logger is not None

    # Verify that boto3 and watchtower were called
    mock_boto_client.assert_called_once_with(
        service_name="logs", region_name="us-east-1"
    )
    mock_watchtower_handler.assert_called_once()


def test_environment_variable_defaults(mock_boto3):
    """Test that the logger correctly uses environment variables for defaults."""
    with patch.dict(
        os.environ,
        {
            "CLOUD_INIT_LOG_GROUP": "env_group",
            "VM_NAME": "env_vm",
            "AWS_REGION": "env_region",
        },
    ):
        logger = CloudAndConsoleLogger("test_env_module")
        assert logger.log_group == "env_group"
        assert logger.log_stream == "env_vm"
        assert logger.region == "env_region"


def test_logging_methods(logger_instance):
    """Test that logging methods (debug, info, etc.) are passed to both loggers."""
    logger_instance.console_logger = MagicMock()
    logger_instance.cloud_logger = MagicMock()

    logger_instance.debug("This is a debug message")
    logger_instance.console_logger.debug.assert_called_once_with(
        "This is a debug message"
    )
    logger_instance.cloud_logger.debug.assert_called_once_with(
        "This is a debug message"
    )

    logger_instance.info("This is an info message")
    logger_instance.console_logger.info.assert_called_once_with(
        "This is an info message"
    )
    logger_instance.cloud_logger.info.assert_called_once_with(
        "This is an info message"
    )


def test_cloud_logging_failure(logger_instance):
    """Test that the logger gracefully handles failures in the cloud logger."""
    logger_instance.console_logger = MagicMock()
    # Ensure cloud_logger.error is a MagicMock before setting side_effect
    logger_instance.cloud_logger.error = MagicMock()
    # Simulate cloud logger failure
    logger_instance.cloud_logger.error.side_effect = Exception("CloudWatch failed")

    logger_instance.error("This is an error message")

    # The console logger should still be called twice
    logger_instance.console_logger.error.assert_has_calls([
        call("This is an error message"),
        call(
            "Failed to log to CloudWatch: CloudWatch failed. Continuing with console "
            "logging only."
        )
    ])


def test_pprint_method(logger_instance):
    """Test the pprint method to ensure it logs formatted output."""
    logger_instance.console_logger = MagicMock()
    logger_instance.cloud_logger = MagicMock()

    test_obj = {"key": "value", "nested": {"a": 1}}
    logger_instance.pprint(test_obj)

    # Check that both loggers were called with the pretty-printed string
    logger_instance.console_logger.log.assert_called_once()
    logger_instance.cloud_logger.log.assert_called_once()


@patch("boto3.client", side_effect=Exception("AWS credentials not found"))
def test_cloud_logging_setup_failure(mock_boto_client):
    """Test fallback when setting up CloudWatch logging fails."""
    # Use a real logger to capture the error message
    console_logger = logging.getLogger("test_fallback")
    with patch.object(console_logger, "error") as mock_error:
        with patch(
            "lablink_client_service.logger_utils.logging.getLogger",
            return_value=console_logger,
        ):
            logger = CloudAndConsoleLogger("test_fallback_module")

            # The cloud logger should be None
            assert logger.cloud_logger is None

            # An error should be logged to the console
            mock_error.assert_called_once_with(
                "Failed to set up CloudWatch logging: AWS credentials not found. "
                "Falling back to console logging only."
            )
