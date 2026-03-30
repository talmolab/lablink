"""Tests for lablink_cli.commands.doctor orchestration and additional checks."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lablink_cli.commands.doctor import (
    _check_aws_credentials,
    _check_config_exists,
    _check_config_valid,
    _check_s3_bucket,
    run_doctor,
)


# ------------------------------------------------------------------
# _check_aws_credentials
# ------------------------------------------------------------------
class TestCheckAwsCredentials:
    @patch("lablink_cli.commands.setup.check_credentials")
    @patch("lablink_cli.commands.setup._get_session")
    def test_valid(self, mock_session, mock_check):
        mock_check.return_value = {
            "account": "123456789012",
            "arn": "arn:aws:iam::123456789012:user/test",
        }
        result = _check_aws_credentials("us-east-1")
        assert result["status"] == "pass"

    @patch("lablink_cli.commands.setup.check_credentials")
    @patch("lablink_cli.commands.setup._get_session")
    def test_invalid_exits(self, mock_session, mock_check):
        mock_check.side_effect = SystemExit(1)
        result = _check_aws_credentials("us-east-1")
        assert result["status"] == "fail"

    @patch("lablink_cli.commands.setup.check_credentials")
    @patch("lablink_cli.commands.setup._get_session")
    def test_exception(self, mock_session, mock_check):
        mock_check.side_effect = Exception("network error")
        result = _check_aws_credentials("us-east-1")
        assert result["status"] == "fail"
        assert "network error" in result["detail"]

    @patch("lablink_cli.commands.setup.check_credentials")
    @patch("lablink_cli.commands.setup._get_session")
    def test_default_region(self, mock_session, mock_check):
        mock_check.side_effect = SystemExit(1)
        result = _check_aws_credentials(None)
        mock_session.assert_called_once_with("us-east-1")


# ------------------------------------------------------------------
# _check_config_exists
# ------------------------------------------------------------------
class TestCheckConfigExists:
    @patch(
        "lablink_cli.commands.doctor.DEFAULT_CONFIG",
        new=Path("/tmp/lablink-test-nonexistent/config.yaml"),
    )
    def test_missing(self):
        result = _check_config_exists()
        assert result["status"] == "fail"

    def test_exists(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("test: true")
        with patch(
            "lablink_cli.commands.doctor.DEFAULT_CONFIG", new=config
        ):
            result = _check_config_exists()
            assert result["status"] == "pass"


# ------------------------------------------------------------------
# _check_config_valid
# ------------------------------------------------------------------
class TestCheckConfigValid:
    @patch(
        "lablink_cli.commands.doctor.DEFAULT_CONFIG",
        new=Path("/tmp/lablink-test-nonexistent/config.yaml"),
    )
    def test_no_config(self):
        result, cfg = _check_config_valid()
        assert result["status"] == "warn"
        assert cfg is None

    @patch("lablink_cli.config.schema.validate_config")
    @patch("lablink_cli.config.schema.load_config")
    def test_valid_config(self, mock_load, mock_validate, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("deployment_name: test")
        mock_load.return_value = MagicMock()
        mock_validate.return_value = []

        with patch(
            "lablink_cli.commands.doctor.DEFAULT_CONFIG", new=config
        ):
            result, cfg = _check_config_valid()
            assert result["status"] == "pass"
            assert cfg is not None

    @patch("lablink_cli.config.schema.validate_config")
    @patch("lablink_cli.config.schema.load_config")
    def test_invalid_config(self, mock_load, mock_validate, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("deployment_name: x")
        mock_load.return_value = MagicMock()
        mock_validate.return_value = ["name too short"]

        with patch(
            "lablink_cli.commands.doctor.DEFAULT_CONFIG", new=config
        ):
            result, cfg = _check_config_valid()
            assert result["status"] == "fail"

    def test_load_error(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("bad: [yaml: {")

        with patch(
            "lablink_cli.commands.doctor.DEFAULT_CONFIG", new=config
        ):
            result, cfg = _check_config_valid()
            assert result["status"] == "fail"
            assert cfg is None


# ------------------------------------------------------------------
# _check_s3_bucket
# ------------------------------------------------------------------
class TestCheckS3Bucket:
    def test_no_config(self):
        result = _check_s3_bucket(None)
        assert result["status"] == "warn"

    def test_no_bucket_name(self):
        cfg = MagicMock(spec=[])
        result = _check_s3_bucket(cfg)
        assert result["status"] == "fail"

    @patch("lablink_cli.commands.setup._get_session")
    def test_bucket_exists(self, mock_session):
        cfg = MagicMock()
        cfg.bucket_name = "my-bucket"
        cfg.app.region = "us-east-1"
        s3 = MagicMock()
        mock_session.return_value.client.return_value = s3
        s3.head_bucket.return_value = {}

        result = _check_s3_bucket(cfg)
        assert result["status"] == "pass"

    @patch("lablink_cli.commands.setup._get_session")
    def test_bucket_not_found(self, mock_session):
        cfg = MagicMock()
        cfg.bucket_name = "my-bucket"
        cfg.app.region = "us-east-1"
        s3 = MagicMock()
        mock_session.return_value.client.return_value = s3
        s3.head_bucket.side_effect = Exception("not found")

        result = _check_s3_bucket(cfg)
        assert result["status"] == "fail"


# ------------------------------------------------------------------
# run_doctor (integration-level)
# ------------------------------------------------------------------
class TestRunDoctor:
    @patch("lablink_cli.commands.doctor._check_ami")
    @patch("lablink_cli.commands.doctor._check_s3_bucket")
    @patch("lablink_cli.commands.doctor._check_aws_credentials")
    @patch("lablink_cli.commands.doctor._check_config_valid")
    @patch("lablink_cli.commands.doctor._check_config_exists")
    @patch("lablink_cli.commands.doctor._check_terraform")
    def test_all_pass(
        self,
        mock_tf,
        mock_cfg_exists,
        mock_cfg_valid,
        mock_aws,
        mock_s3,
        mock_ami,
    ):
        mock_tf.return_value = {"check": "Terraform", "status": "pass", "detail": "ok"}
        mock_cfg_exists.return_value = {
            "check": "Config", "status": "pass", "detail": "ok"
        }
        mock_cfg = MagicMock()
        mock_cfg.app.region = "us-east-1"
        mock_cfg_valid.return_value = (
            {"check": "Validates", "status": "pass", "detail": "ok"},
            mock_cfg,
        )
        mock_aws.return_value = {"check": "AWS", "status": "pass", "detail": "ok"}
        mock_s3.return_value = {"check": "S3", "status": "pass", "detail": "ok"}
        mock_ami.return_value = {"check": "AMI", "status": "pass", "detail": "ok"}

        # Should not raise
        run_doctor()

    @patch("lablink_cli.commands.doctor._check_ami")
    @patch("lablink_cli.commands.doctor._check_s3_bucket")
    @patch("lablink_cli.commands.doctor._check_aws_credentials")
    @patch("lablink_cli.commands.doctor._check_config_valid")
    @patch("lablink_cli.commands.doctor._check_config_exists")
    @patch("lablink_cli.commands.doctor._check_terraform")
    def test_some_fail(
        self,
        mock_tf,
        mock_cfg_exists,
        mock_cfg_valid,
        mock_aws,
        mock_s3,
        mock_ami,
    ):
        mock_tf.return_value = {"check": "Terraform", "status": "fail", "detail": ""}
        mock_cfg_exists.return_value = {"check": "Config", "status": "pass", "detail": ""}
        mock_cfg_valid.return_value = (
            {"check": "Validates", "status": "warn", "detail": ""},
            None,
        )
        mock_aws.return_value = {"check": "AWS", "status": "fail", "detail": ""}
        mock_s3.return_value = {"check": "S3", "status": "warn", "detail": ""}
        mock_ami.return_value = {"check": "AMI", "status": "warn", "detail": ""}

        # Should not raise even with failures
        run_doctor()
