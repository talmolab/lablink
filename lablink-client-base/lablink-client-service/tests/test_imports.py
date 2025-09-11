"""Module that tests the imports of the package."""

import pytest


def test_import():
    try:
        import lablink_client_service
    except ImportError as e:
        pytest.fail(f"Import failed: {e}")
