"""Tests for lablink_cli.config.schema helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
import yaml

from lablink_cli.config.schema import (
    AMI_MAP,
    AWS_REGIONS,
    CPU_INSTANCE_TYPES,
    DEPLOYMENT_NAME_RE,
    GPU_INSTANCE_TYPES,
    VALID_ENVIRONMENTS,
    config_to_dict,
    load_config,
    save_config,
    validate_config,
)


# ------------------------------------------------------------------
# config_to_dict
# ------------------------------------------------------------------
class TestConfigToDict:
    def test_plain_value(self):
        assert config_to_dict(42) == 42
        assert config_to_dict("hello") == "hello"

    def test_flat_dataclass(self):
        @dataclass
        class Flat:
            x: int = 1
            y: str = "a"

        result = config_to_dict(Flat())
        assert result == {"x": 1, "y": "a"}

    def test_nested_dataclass(self):
        @dataclass
        class Inner:
            val: int = 10

        @dataclass
        class Outer:
            inner: Inner = None

            def __post_init__(self):
                if self.inner is None:
                    self.inner = Inner()

        result = config_to_dict(Outer())
        assert result == {"inner": {"val": 10}}


# ------------------------------------------------------------------
# load_config / save_config round-trip
# ------------------------------------------------------------------
class TestLoadSaveConfig:
    def test_round_trip(self, tmp_path):
        from lablink_allocator_service.conf.structured_config import Config

        cfg = Config()
        cfg.deployment_name = "test-lab"
        cfg.environment = "dev"
        cfg.app.region = "us-west-2"

        path = tmp_path / "config.yaml"
        save_config(cfg, path)

        assert path.exists()

        loaded = load_config(path)
        assert loaded.deployment_name == "test-lab"
        assert loaded.environment == "dev"
        assert loaded.app.region == "us-west-2"

    def test_save_creates_parent_dirs(self, tmp_path):
        from lablink_allocator_service.conf.structured_config import Config

        path = tmp_path / "deep" / "nested" / "config.yaml"
        save_config(Config(), path)
        assert path.exists()

    def test_load_nested_values(self, tmp_path):
        data = {
            "deployment_name": "nested-test",
            "dns": {"enabled": True, "domain": "test.example.com"},
        }
        path = tmp_path / "config.yaml"
        with open(path, "w") as f:
            yaml.dump(data, f)

        cfg = load_config(path)
        assert cfg.deployment_name == "nested-test"
        assert cfg.dns.enabled is True
        assert cfg.dns.domain == "test.example.com"

    def test_load_deeply_nested(self, tmp_path):
        """Test 3-level nesting (e.g. monitoring.thresholds.*)."""
        data = {
            "monitoring": {
                "enabled": True,
                "thresholds": {"cpu_percent": 95},
            },
        }
        path = tmp_path / "config.yaml"
        with open(path, "w") as f:
            yaml.dump(data, f)

        cfg = load_config(path)
        assert cfg.monitoring.enabled is True
        assert cfg.monitoring.thresholds.cpu_percent == 95


# ------------------------------------------------------------------
# validate_config
# ------------------------------------------------------------------
class TestValidateConfig:
    def _make_valid_cfg(self):
        from lablink_allocator_service.conf.structured_config import Config

        cfg = Config()
        cfg.deployment_name = "valid-lab"
        cfg.environment = "dev"
        cfg.dns.enabled = False
        cfg.ssl.provider = "none"
        return cfg

    def test_valid_config(self):
        cfg = self._make_valid_cfg()
        assert validate_config(cfg) == []

    def test_missing_deployment_name(self):
        cfg = self._make_valid_cfg()
        cfg.deployment_name = ""
        errors = validate_config(cfg)
        assert any("deployment_name is required" in e for e in errors)

    def test_short_deployment_name(self):
        cfg = self._make_valid_cfg()
        cfg.deployment_name = "ab"
        errors = validate_config(cfg)
        assert any("3-32 characters" in e for e in errors)

    def test_long_deployment_name(self):
        cfg = self._make_valid_cfg()
        cfg.deployment_name = "a" * 33
        errors = validate_config(cfg)
        assert any("3-32 characters" in e for e in errors)

    def test_invalid_deployment_name_uppercase(self):
        cfg = self._make_valid_cfg()
        cfg.deployment_name = "MyLab"
        errors = validate_config(cfg)
        assert any("kebab-case" in e for e in errors)

    def test_invalid_environment(self):
        cfg = self._make_valid_cfg()
        cfg.environment = "staging"
        errors = validate_config(cfg)
        assert any("environment must be one of" in e for e in errors)

    def test_all_valid_environments(self):
        for env in VALID_ENVIRONMENTS:
            cfg = self._make_valid_cfg()
            cfg.environment = env
            errors = validate_config(cfg)
            assert not any("environment" in e for e in errors)

    def test_dns_enabled_no_domain(self):
        cfg = self._make_valid_cfg()
        cfg.dns.enabled = True
        cfg.dns.domain = ""
        errors = validate_config(cfg)
        assert any("DNS enabled but no domain" in e for e in errors)

    def test_ssl_requires_dns(self):
        cfg = self._make_valid_cfg()
        cfg.dns.enabled = False
        cfg.ssl.provider = "letsencrypt"
        errors = validate_config(cfg)
        assert any("requires DNS" in e for e in errors)

    def test_letsencrypt_requires_email(self):
        cfg = self._make_valid_cfg()
        cfg.dns.enabled = True
        cfg.dns.domain = "test.example.com"
        cfg.ssl.provider = "letsencrypt"
        cfg.ssl.email = ""
        errors = validate_config(cfg)
        assert any("email" in e for e in errors)

    def test_acm_requires_arn(self):
        cfg = self._make_valid_cfg()
        cfg.dns.enabled = True
        cfg.dns.domain = "test.example.com"
        cfg.ssl.provider = "acm"
        cfg.ssl.certificate_arn = ""
        errors = validate_config(cfg)
        assert any("certificate ARN" in e for e in errors)

    def test_cloudflare_terraform_managed(self):
        cfg = self._make_valid_cfg()
        cfg.dns.enabled = True
        cfg.dns.domain = "test.example.com"
        cfg.dns.terraform_managed = True
        cfg.ssl.provider = "cloudflare"
        errors = validate_config(cfg)
        assert any("terraform_managed=false" in e for e in errors)


# ------------------------------------------------------------------
# Reference data
# ------------------------------------------------------------------
class TestReferenceData:
    def test_deployment_name_regex(self):
        assert DEPLOYMENT_NAME_RE.match("valid-name")
        assert DEPLOYMENT_NAME_RE.match("abc")
        assert not DEPLOYMENT_NAME_RE.match("Ab")
        assert not DEPLOYMENT_NAME_RE.match("-invalid")
        assert not DEPLOYMENT_NAME_RE.match("invalid-")

    def test_ami_map_has_regions(self):
        assert len(AMI_MAP) > 0
        for region, ami in AMI_MAP.items():
            assert ami.startswith("ami-")

    def test_gpu_instance_types_structure(self):
        assert len(GPU_INSTANCE_TYPES) > 0
        for it in GPU_INSTANCE_TYPES:
            assert "type" in it
            assert "gpu" in it
            assert "vcpu" in it

    def test_cpu_instance_types_structure(self):
        assert len(CPU_INSTANCE_TYPES) > 0
        for it in CPU_INSTANCE_TYPES:
            assert "type" in it
            assert "vcpu" in it

    def test_aws_regions_structure(self):
        assert len(AWS_REGIONS) > 0
        for r in AWS_REGIONS:
            assert "id" in r
            assert "name" in r
