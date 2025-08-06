import logging
import pprint
import os

import boto3
import watchtower


class CloudAndConsoleLogger:
    def __init__(
        self,
        module_name: str,
        level=logging.DEBUG,
        format=None,
        log_group=None,
        log_stream=None,
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
        self.log_stream = log_stream or os.environ.get("VM_NAME", "my-app-stream")
        self.region = region or os.environ.get("AWS_REGION", "us-west-2")

        # Set up both console and cloud logging
        self.console_logger = self.setup_console_logger(
            level=level, formatter=formatter
        )
        self.cloud_logger = self.setup_cloud_logging(level=level, formatter=formatter)

    def __getattr__(self, name):
        """Pass the log call to both the console and cloud loggers."""

        def wrapper(*args, **kwargs):
            getattr(self.console_logger, name)(*args, **kwargs)
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
        self.log(level, pretty_str)

    def setup_console_logger(
        self, level=logging.DEBUG, formatter: logging.Formatter = None
    ):
        """Set up a console logger."""
        # Create a console logger
        logger = logging.getLogger(self.name)
        logger.setLevel(level)

        # Create a console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)

        # Set Formatter
        console_handler.setFormatter(formatter)

        # Add the console handler to the logger
        logger.addHandler(console_handler)

        return logger

    def setup_cloud_logging(
        self, level=logging.DEBUG, formatter: logging.Formatter = None
    ):
        """Set up logging to AWS CloudWatch Logs."""
        session = boto3.Session(region_name=self.region)
        handler = watchtower.CloudWatchLogHandler(
            log_group=self.log_group,
            stream_name=self.log_stream,
            boto3_client=session,
            create_log_group=True,
        )
        handler.setFormatter(formatter)

        logger = logging.getLogger(f"{self.name}_cloud_logger")
        logger.setLevel(level)
        logger.addHandler(handler)
        return logger
