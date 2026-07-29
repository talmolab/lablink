"""Shared fixtures for the client test suite."""

import logging

import pytest

PACKAGE_LOGGER = "lablink_client_service"


@pytest.fixture(autouse=True)
def restore_global_logging_state():
    """Undo the process-global logging each service's main() configures."""
    root = logging.getLogger()
    package = logging.getLogger(PACKAGE_LOGGER)
    root_level, root_handlers, package_level = (
        root.level,
        list(root.handlers),
        package.level,
    )
    yield
    root.setLevel(root_level)
    root.handlers[:] = root_handlers
    package.setLevel(package_level)
