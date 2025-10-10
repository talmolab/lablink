import pytest
from unittest.mock import MagicMock
from omegaconf import OmegaConf
import base64
import yaml
from pathlib import Path


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
                "terraform_managed": False,
                "domain": "",
                "zone_id": "",
                "app_name": "lablink",
                "pattern": "auto",
                "custom_subdomain": "",
                "create_zone": False,
            },
            "eip": {
                "strategy": "dynamic",
                "tag_name": "lablink-eip",
            },
            "ssl": {
                "provider": "none",
                "email": "",
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
    monkeypatch.setattr(
        "lablink_allocator_service.get_config.get_config",
        lambda: omega_config,
        raising=True,
    )

    from lablink_allocator_service import main

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


@pytest.fixture
def valid_config_dict():
    """Valid configuration dictionary including allocator section."""
    return {
        "db": {
            "dbname": "lablink_db",
            "user": "lablink",
            "password": "test_password",
            "host": "localhost",
            "port": 5432,
            "table_name": "vms",
            "message_channel": "vm_updates",
        },
        "machine": {
            "machine_type": "g4dn.xlarge",
            "image": "ghcr.io/talmolab/lablink-client-base-image:latest",
            "ami_id": "ami-0601752c11b394251",
            "repository": "https://github.com/talmolab/sleap-tutorial-data.git",
            "software": "sleap",
            "extension": "slp",
        },
        "app": {
            "admin_user": "admin",
            "admin_password": "test_admin_password",
            "region": "us-west-2",
        },
        "dns": {
            "enabled": False,
            "terraform_managed": False,
            "domain": "lablink.example.com",
            "zone_id": "",
            "app_name": "lablink",
            "pattern": "auto",
            "custom_subdomain": "",
            "create_zone": False,
        },
        "eip": {
            "strategy": "dynamic",
            "tag_name": "lablink-eip-dynamic",
        },
        "ssl": {
            "provider": "none",
            "email": "admin@example.com",
            "staging": True,
        },
        "allocator": {
            "image_tag": "linux-amd64-latest-test",
        },
        "bucket_name": "tf-state-lablink-allocator-bucket",
    }


@pytest.fixture
def invalid_config_dict():
    """Invalid configuration with unknown key (recreates Docker error)."""
    return {
        "db": {
            "dbname": "lablink_db",
            "user": "lablink",
            "password": "test_password",
            "host": "localhost",
            "port": 5432,
            "table_name": "vms",
            "message_channel": "vm_updates",
        },
        "machine": {
            "machine_type": "g4dn.xlarge",
            "image": "ghcr.io/talmolab/lablink-client-base-image:latest",
            "ami_id": "ami-0601752c11b394251",
            "software": "sleap",
            "extension": "slp",
        },
        "app": {
            "admin_user": "admin",
            "admin_password": "test_admin_password",
            "region": "us-west-2",
        },
        # This key does not exist in the schema
        "unknown_section": {
            "unknown_key": "unknown_value",
        },
        "bucket_name": "tf-state-lablink-allocator-bucket",
    }


@pytest.fixture
def config_with_unknown_top_level_key():
    """Config with unknown top-level section (terraform_vars doesn't exist in schema)."""
    return {
        "db": {
            "dbname": "lablink_db",
            "user": "lablink",
            "password": "test_password",
            "host": "localhost",
            "port": 5432,
            "table_name": "vms",
            "message_channel": "vm_updates",
        },
        "machine": {
            "machine_type": "g4dn.xlarge",
            "image": "ghcr.io/talmolab/lablink-client-base-image:latest",
            "ami_id": "ami-test",
            "software": "sleap",
            "extension": "slp",
        },
        "app": {
            "admin_user": "admin",
            "admin_password": "test_password",
            "region": "us-west-2",
        },
        # This top-level key does NOT exist in Config schema
        "terraform_vars": {
            "instance_count": 5,
            "custom_setting": "value",
        },
        "bucket_name": "test-bucket",
    }


@pytest.fixture
def config_with_unknown_nested_key():
    """Config with unknown nested field (db.unknown_field doesn't exist in schema)."""
    return {
        "db": {
            "dbname": "lablink_db",
            "user": "lablink",
            "password": "test_password",
            "host": "localhost",
            "port": 5432,
            "table_name": "vms",
            "message_channel": "vm_updates",
            # This nested key does NOT exist in DatabaseConfig schema
            "unknown_field": "this_should_fail",
        },
        "machine": {
            "machine_type": "g4dn.xlarge",
            "image": "ghcr.io/talmolab/lablink-client-base-image:latest",
            "ami_id": "ami-test",
            "software": "sleap",
            "extension": "slp",
        },
        "app": {
            "admin_user": "admin",
            "admin_password": "test_password",
            "region": "us-west-2",
        },
        "bucket_name": "test-bucket",
    }


@pytest.fixture
def write_config_file(tmp_path):
    """Helper function to write config dict to a temporary YAML file."""

    def _write(config_dict, filename="config.yaml"):
        config_file = tmp_path / filename
        with open(config_file, "w") as f:
            yaml.dump(config_dict, f)
        return str(config_file)

    return _write
