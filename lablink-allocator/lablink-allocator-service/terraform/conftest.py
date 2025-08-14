import os
import pytest


@pytest.fixture(scope="session")
def fixture_dir():
    return os.path.join(os.path.dirname(__file__), "fixtures")
