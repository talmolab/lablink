"""Module that tests the imports of the package."""

import pytest


def test_import():
    try:
        import lablink_client_service
        from lablink_client_service import check_gpu
        from lablink_client_service.logger_utils import CloudAndConsoleLogger

    except ImportError as e:
        pytest.fail(f"Import failed: {e}")
