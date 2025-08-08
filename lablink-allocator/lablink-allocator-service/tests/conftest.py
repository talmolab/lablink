import pytest
from unittest.mock import MagicMock, patch
from omegaconf import OmegaConf
import base64


@pytest.fixture(scope="session")
def omega_config():
    """Fixture for the Omega configuration."""
    return OmegaConf.create(
        {
            "db": {
                "dbname": "test_db",
                "user": "test_user",
                "password": "test_password",
                "host": "localhost",
                "port": 5432,
                "table_name": "test_table",
            },
            "machine": {
                "machine_type": "g4dn.xlarge",
                "image": "test-custom-image",
                "ami_id": "ami-test",
                "repository": "https://github.com/example/repo.git",
                "software": "sleap",
            },
            "app": {
                "admin_user": "test_admin",
                "admin_password": "test_pass",
            },
        }
    )


@pytest.fixture
def patch_get_config(omega_config):
    """Patch the get_config function to return the mock Omega configuration."""
    with patch("main.cfg", omega_config):
        yield


@pytest.fixture
def app():
    """Configures the Flask application for testing."""
    import main
    from main import app as flask_app

    flask_app.config.update(
        {
            "TESTING": True,
        }
    )

    main.database = MagicMock()  # Mock the database connection
    yield flask_app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_headers(omega_config):
    user = omega_config.app.admin_user
    pw = omega_config.app.admin_password
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}"}
