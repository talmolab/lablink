import pytest
from pathlib import Path


@pytest.fixture(scope="module")
def fixture_dir():
    """Return the path to the fixtures directory."""
    return Path(__file__).parent / "fixtures"
