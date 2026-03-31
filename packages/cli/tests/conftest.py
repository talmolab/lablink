"""Shared fixtures for CLI tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def mock_cfg():
    """Minimal Config-like object for testing."""
    cfg = MagicMock()
    cfg.deployment_name = "mylab"
    cfg.environment = "dev"
    cfg.app.region = "us-east-1"
    cfg.app.admin_user = "admin"
    cfg.app.admin_password = "secret"
    cfg.machine.software = "sleap"
    cfg.machine.machine_type = "g4dn.xlarge"
    cfg.dns.enabled = False
    cfg.dns.domain = ""
    cfg.dns.terraform_managed = False
    cfg.dns.zone_id = ""
    cfg.ssl.provider = "none"
    cfg.ssl.email = ""
    cfg.ssl.certificate_arn = ""
    cfg.monitoring.enabled = False
    cfg.startup_script.enabled = False
    cfg.startup_script.path = ""
    cfg.bucket_name = "lablink-tf-state-123456789012"
    return cfg
