import logging
import pprint
import sys


class CloudAndConsoleLogger:
    """Console logger for LabLink client services.

    Maintains the same interface as the previous CloudWatch+Console logger
    for backwards compatibility. Logs are shipped to the allocator via the
    log_shipper.sh script that tails Docker container json-logs.
    """

    def __init__(
        self,
        module_name: str,
        level=logging.DEBUG,
        format=None,
        log_group=None,
        region=None,
    ):
        self.name = module_name

        final_format = format or "%(name)s[%(levelname)s]: %(message)s"
        formatter = logging.Formatter(final_format)

        # Set up console logging
        self.console_logger = self.setup_console_logger(
            level=level, formatter=formatter
        )

    def __getattr__(self, name):
        """Pass the log call to the console logger."""

        def wrapper(*args, **kwargs):
            getattr(self.console_logger, name)(*args, **kwargs)
            sys.stdout.flush()

        return wrapper

    def pprint(self, obj: object, level: int = logging.INFO) -> None:
        """Pretty-print an object and log the output.

        Args:
            obj: The object to pretty-print and log.
            level: The logging level. Defaults to logging.INFO.
        """
        pp = pprint.PrettyPrinter(indent=4)
        pretty_str = pp.pformat(obj)
        self.console_logger.log(level, pretty_str)

    def setup_console_logger(
        self, level=logging.DEBUG, formatter: logging.Formatter = None
    ):
        """Set up a console logger."""
        logger = logging.getLogger(self.name)
        logger.setLevel(level)
        logger.propagate = False

        if not logger.handlers:
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setLevel(level)
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)

        return logger
