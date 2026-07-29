"""Logging configuration for the client service entry points.

Call `configure_service_logging()` from a console script's `main()` — never at
import time. A library module that calls `logging.basicConfig()` at module
scope mutates global logging state for whatever process imports it, and
`basicConfig()` is a no-op once root has a handler, so the winner ends up being
decided by import order (see allocator issue #409).

This replaces `logger_utils.CloudAndConsoleLogger`, a leftover from when client
logs were shipped to CloudWatch. That class had stopped doing anything
CloudWatch-related, but it survived as a console-logger wrapper that services
assigned over their module-level `logger`, taking `log_group`/`region` args it
ignored. Logs now reach the allocator via log_shipper.sh tailing the container's
Docker json-logs, so plain stdlib logging is all that is needed.
"""

import logging

# start.sh launches each service with `2>&1 | sed -u 's/^/[check_gpu] /'`, so
# the stream is already merged and every line already carries the service name.
FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"

PACKAGE_LOGGER = "lablink_client_service"


def configure_service_logging(level: int = logging.DEBUG) -> None:
    """Install the process's log handler and set this package's log level.

    Two levels, set deliberately:

    * Root gets the single handler and the format, held at INFO. Root is the
      floor for third-party loggers — `requests`, `urllib3` — and at DEBUG
      urllib3 logs every connection and request, burying our own output.
    * The `lablink_client_service` logger carries `level`. Every module logs
      through its own `getLogger(__name__)` with no explicit level, so setting
      it once here reaches all of them.

    Holding root at INFO mutes nothing of ours: a record that its own logger
    admits still reaches root's handler regardless of root's level.

    Args:
        level: Level for this package's loggers. Defaults to DEBUG, which is
            what these services have always run at — heartbeat's two
            `logger.debug()` calls are POST-failure paths worth keeping
            visible on a client VM.
    """
    logging.basicConfig(level=logging.INFO, format=FORMAT, datefmt=DATEFMT)
    logging.getLogger(PACKAGE_LOGGER).setLevel(level)
