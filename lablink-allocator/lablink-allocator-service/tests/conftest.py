import pytest
from unittest.mock import MagicMock
from omegaconf import OmegaConf
import base64


@pytest.fixture(scope="session")
def omega_config():
    """Session-scoped OmegaConf for testing."""
    return OmegaConf.create(
        {
            "db": {
                "dbname": "test_db",
                "user": "test_user",
                "password": "test_password",
                "host": "localhost",
                "port": 5432,
                "table_name": "test_table",
                "message_channel": "vm_updates",
            },
            "machine": {
                "machine_type": "g4dn.xlarge",
                "image": "test-custom-image",
                "ami_id": "ami-test",
                "repository": "https://github.com/example/repo.git",
                "software": "sleap",
                "extension": "slp",
            },
            "app": {
                "admin_user": "test_admin",
                "admin_password": "test_pass",
                "region": "us-west-2",
            },
            "dns": {
                "enabled": False,
                "domain": "",
                "app_name": "lablink",
                "pattern": "auto",
                "custom_subdomain": "",
                "create_zone": False,
            },
            "bucket_name": "test-bucket",
        }
    )


@pytest.fixture
def app(monkeypatch, omega_config):
    """
    Import `main` lazily so we can patch module-level globals
    (like cfg and database) before first use.
    """

    # Patch the module-level cfg to use our test OmegaConf
    monkeypatch.setattr("get_config.get_config", lambda: omega_config, raising=True)

    import main

    # Patch the cfg to use test config
    monkeypatch.setattr(main, "cfg", omega_config, raising=False)

    # Patch the users dict to use test credentials
    from werkzeug.security import generate_password_hash
    test_users = {
        omega_config.app.admin_user: generate_password_hash(
            omega_config.app.admin_password
        )
    }
    monkeypatch.setattr(main, "users", test_users, raising=False)

    # If your code references `main.database`, stub it out:
    if not hasattr(main, "database"):
        monkeypatch.setattr(main, "database", MagicMock(), raising=False)
    else:
        main.database = MagicMock()

    flask_app = main.app
    flask_app.config.update(
        TESTING=True,
        SECRET_KEY=omega_config.app.get("secret_key", "test-secret"),
    )

    with flask_app.app_context():
        yield flask_app


@pytest.fixture
def client(app):
    """HTTP client for the Flask app."""
    return app.test_client()


@pytest.fixture
def admin_headers(omega_config):
    """Convenience Basic-Auth header using cfg credentials."""

    user = omega_config.app.admin_user
    pw = omega_config.app.admin_password
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}"}
