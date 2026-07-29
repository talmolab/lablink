"""Module that tests the imports of the package."""

import pytest


def test_import():
    try:
        import lablink_client_service
        from lablink_client_service import check_gpu
        from lablink_client_service import heartbeat, update_inuse_status

    except ImportError as e:
        pytest.fail(f"Import failed: {e}")
