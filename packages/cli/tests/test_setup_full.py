"""Tests for lablink_cli.commands.setup run_setup orchestration."""

from __future__ import annotations

from unittest.mock import patch


from lablink_cli.commands.setup import run_setup


class TestRunSetup:
    @patch("lablink_cli.config.schema.save_config")
    @patch("lablink_cli.commands.setup.create_dynamodb_table")
    @patch("lablink_cli.commands.setup.create_s3_bucket")
    @patch("lablink_cli.commands.setup.check_credentials")
    @patch("lablink_cli.commands.setup._get_session")
    def test_basic_setup(
        self,
        mock_session,
        mock_creds,
        mock_s3,
        mock_dynamo,
        mock_save,
        mock_cfg,
        tmp_path,
    ):
        mock_creds.return_value = {
            "account": "123456789012",
            "arn": "arn:aws:iam::123456789012:user/test",
        }
        mock_s3.return_value = True
        mock_dynamo.return_value = True

        config_path = tmp_path / "config.yaml"
        run_setup(mock_cfg, config_path=config_path)

        mock_creds.assert_called_once()
        mock_s3.assert_called_once()
        mock_dynamo.assert_called_once()
        assert mock_cfg.bucket_name == "lablink-tf-state-123456789012"

    @patch("lablink_cli.commands.setup.create_route53_zone")
    @patch("lablink_cli.config.schema.save_config")
    @patch("lablink_cli.commands.setup.create_dynamodb_table")
    @patch("lablink_cli.commands.setup.create_s3_bucket")
    @patch("lablink_cli.commands.setup.check_credentials")
    @patch("lablink_cli.commands.setup._get_session")
    def test_with_dns(
        self,
        mock_session,
        mock_creds,
        mock_s3,
        mock_dynamo,
        mock_save,
        mock_route53,
        mock_cfg,
        tmp_path,
    ):
        mock_creds.return_value = {
            "account": "123456789012",
            "arn": "arn:aws:iam::123456789012:user/test",
        }
        mock_cfg.dns.enabled = True
        mock_cfg.dns.terraform_managed = True
        mock_cfg.dns.domain = "test.example.com"
        mock_cfg.dns.zone_id = ""
        mock_route53.return_value = "Z123"

        run_setup(mock_cfg, config_path=tmp_path / "config.yaml")
        mock_route53.assert_called_once()

    @patch("lablink_cli.config.schema.save_config")
    @patch("lablink_cli.commands.setup.create_dynamodb_table")
    @patch("lablink_cli.commands.setup.create_s3_bucket")
    @patch("lablink_cli.commands.setup.check_credentials")
    @patch("lablink_cli.commands.setup._get_session")
    def test_default_config_path(
        self,
        mock_session,
        mock_creds,
        mock_s3,
        mock_dynamo,
        mock_save,
        mock_cfg,
    ):
        mock_creds.return_value = {
            "account": "123456789012",
            "arn": "arn:aws:iam::123456789012:user/test",
        }
        mock_cfg.dns.enabled = False
        mock_cfg.dns.terraform_managed = False

        run_setup(mock_cfg, config_path=None)
        # save_config should be called with the DEFAULT_CONFIG path
        mock_save.assert_called_once()
