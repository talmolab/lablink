import logging
import pprint
import os
import sys

import boto3
import watchtower


class CloudAndConsoleLogger:
    def __init__(
        self,
        module_name: str,
        level=logging.DEBUG,
        format=None,
        log_group=None,
        region=None,
    ):
        self.name = module_name

        format = format or "%(module)s[%(levelname)s]: %(message)s"
        formatter = logging.Formatter(format)

        # Get credentials
        # Get group/stream names from env vars or use defaults
        self.log_group = log_group or os.environ.get(
            "CLOUD_INIT_LOG_GROUP", "my-app-logs"
        )

        log_stream_name = f"{os.getenv('VM_NAME', 'my-app-stream')}/{module_name}"
        self.log_stream = log_stream_name
        self.region = region or os.environ.get("AWS_REGION", "us-west-2")

        # Set up both console and cloud logging
        self.console_logger = self.setup_console_logger(
            level=level, formatter=formatter
        )
        self.cloud_logger = self.setup_cloud_logging(level=level, formatter=formatter)

    def __getattr__(self, name):
        """Pass the log call to both the console and cloud loggers."""

        def wrapper(*args, **kwargs):
            if hasattr(self.console_logger, name):
                getattr(self.console_logger, name)(*args, **kwargs)
            if self.cloud_logger and hasattr(self.cloud_logger, name):
                getattr(self.cloud_logger, name)(*args, **kwargs)

        return wrapper

    def pprint(self, obj, level=logging.INFO):
        """Pretty-print an object and log the output.

        Args:
            obj: The object to pretty-print and log.
            level (int, optional): The logging level. Defaults to logging.INFO.
        """

        pp = pprint.PrettyPrinter(indent=4)
        pretty_str = pp.pformat(obj)
        self.console_logger.log(level, pretty_str)
        self.cloud_logger.log(level, pretty_str)

    def setup_console_logger(
        self, level=logging.DEBUG, formatter: logging.Formatter = None
    ):
        """Set up a console logger."""
        # Create a console logger
        logger = logging.getLogger(self.name)
        logger.setLevel(level)

        # Create a console handler
        if not logger.handlers:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(level)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)

        return logger

    def setup_cloud_logging(
        self, level=logging.DEBUG, formatter: logging.Formatter = None
    ):
        """Set up logging to AWS CloudWatch Logs."""
        try:
            session = boto3.client(service_name="logs", region_name=self.region)
            handler = watchtower.CloudWatchLogHandler(
                log_group_name=self.log_group,
                log_stream_name=self.log_stream,
                boto3_client=session,
                create_log_group=True,
                create_log_stream=True,
            )
            handler.setFormatter(formatter)

            logger = logging.getLogger(f"{self.name}_cloud_logger")
            logger.setLevel(level)

            if not logger.handlers:
                logger.addHandler(handler)

            return logger
        except Exception as e:
            console_logger = logging.getLogger(self.name)
            console_logger.error(
                f"Failed to set up CloudWatch logging: {e}. "
                "Falling back to console logging only."
            )
            return None
