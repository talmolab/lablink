"""Module that tests the imports of the package."""

import pytest
from unittest import mock


def test_import():
    try:
        import lablink_client_service
        from lablink_client_service import database
    except ImportError as e:
        pytest.fail(f"Import failed: {e}")
