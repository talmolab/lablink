"""Module that tests the imports of the package."""


def test_import():
    try:
        import lablink_client_service
        from lablink_client_service import subscribe
    except ImportError as e:
        pytest.fail(f"Import failed: {e}")
