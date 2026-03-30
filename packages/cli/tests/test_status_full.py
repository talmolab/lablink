"""Tests for lablink_cli.commands.status run_status and additional helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lablink_cli.commands.status import (
    REGION_NAME_MAP,
    _get_ec2_price,
    run_status,
)


# ------------------------------------------------------------------
# _get_ec2_price
# ------------------------------------------------------------------
class TestGetEc2Price:
    def test_returns_price(self):
        pricing = MagicMock()
        pricing.get_products.return_value = {
            "PriceList": [
                '{"terms": {"OnDemand": {"term1": {"priceDimensions": '
                '{"dim1": {"pricePerUnit": {"USD": "0.526"}}}}}}}'
            ]
        }
        result = _get_ec2_price(pricing, "g4dn.xlarge", "US East (N. Virginia)")
        assert result == 0.526

    def test_empty_price_list(self):
        pricing = MagicMock()
        pricing.get_products.return_value = {"PriceList": []}
        result = _get_ec2_price(pricing, "g4dn.xlarge", "US East (N. Virginia)")
        assert result is None

    def test_api_error(self):
        from botocore.exceptions import ClientError

        pricing = MagicMock()
        pricing.get_products.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": ""}},
            "GetProducts",
        )
        result = _get_ec2_price(pricing, "g4dn.xlarge", "US East (N. Virginia)")
        assert result is None

    def test_zero_price_skipped(self):
        pricing = MagicMock()
        pricing.get_products.return_value = {
            "PriceList": [
                '{"terms": {"OnDemand": {"term1": {"priceDimensions": '
                '{"dim1": {"pricePerUnit": {"USD": "0.0"}}, '
                '"dim2": {"pricePerUnit": {"USD": "1.5"}}}}}}}'
            ]
        }
        result = _get_ec2_price(pricing, "t3.large", "US East (N. Virginia)")
        assert result == 1.5


# ------------------------------------------------------------------
# REGION_NAME_MAP
# ------------------------------------------------------------------
class TestRegionNameMap:
    def test_common_regions_present(self):
        assert "us-east-1" in REGION_NAME_MAP
        assert "us-west-2" in REGION_NAME_MAP

    def test_values_are_strings(self):
        for region, name in REGION_NAME_MAP.items():
            assert isinstance(name, str)
            assert len(name) > 0


# ------------------------------------------------------------------
# run_status (integration-level)
# ------------------------------------------------------------------
class TestRunStatus:
    @patch("lablink_cli.commands.status.estimate_costs")
    @patch("lablink_cli.commands.status.get_client_vms")
    @patch("lablink_cli.commands.status.get_terraform_outputs")
    @patch("lablink_cli.commands.status._get_deploy_dir")
    def test_no_deployment(
        self, mock_deploy_dir, mock_outputs, mock_vms, mock_costs, mock_cfg, tmp_path
    ):
        mock_deploy_dir.return_value = tmp_path / "nonexistent"
        mock_vms.return_value = []
        mock_costs.return_value = [
            {"resource": "EC2", "daily": 2.0, "note": "always on"}
        ]

        # Should not raise
        run_status(mock_cfg)

    @patch("lablink_cli.commands.status.estimate_costs")
    @patch("lablink_cli.commands.status.get_client_vms")
    @patch("lablink_cli.commands.status.get_terraform_outputs")
    @patch("lablink_cli.commands.status._get_deploy_dir")
    def test_with_deployment(
        self, mock_deploy_dir, mock_outputs, mock_vms, mock_costs, mock_cfg, tmp_path
    ):
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()
        mock_deploy_dir.return_value = deploy_dir
        mock_outputs.return_value = {
            "ec2_public_ip": "1.2.3.4",
            "private_key_pem": "-----BEGIN RSA PRIVATE KEY-----",
        }
        mock_vms.return_value = [
            {
                "name": "client-1",
                "instance_id": "i-123",
                "type": "g4dn.xlarge",
                "state": "running",
                "public_ip": "5.6.7.8",
            }
        ]
        mock_costs.return_value = [
            {"resource": "EC2", "daily": 2.0, "note": "always on"}
        ]
        mock_cfg.dns.enabled = False
        mock_cfg.ssl.provider = "none"

        run_status(mock_cfg)

    @patch("lablink_cli.commands.status.estimate_costs")
    @patch("lablink_cli.commands.status.get_client_vms")
    @patch("lablink_cli.commands.status.get_terraform_outputs")
    @patch("lablink_cli.commands.status._get_deploy_dir")
    def test_with_dns_and_ssl(
        self, mock_deploy_dir, mock_outputs, mock_vms, mock_costs, mock_cfg, tmp_path
    ):
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()
        mock_deploy_dir.return_value = deploy_dir
        mock_outputs.return_value = {"ec2_public_ip": "1.2.3.4"}
        mock_vms.return_value = []
        mock_costs.return_value = [
            {"resource": "EC2", "daily": 2.0, "note": "always on"}
        ]
        mock_cfg.dns.enabled = True
        mock_cfg.dns.domain = "test.example.com"
        mock_cfg.ssl.provider = "letsencrypt"

        with patch("lablink_cli.commands.status.check_dns") as mock_dns, \
             patch("lablink_cli.commands.status.check_http") as mock_http, \
             patch("lablink_cli.commands.status.check_ssl_cert") as mock_ssl:
            mock_dns.return_value = {"check": "DNS", "status": "pass", "detail": "ok"}
            mock_http.return_value = {"check": "HTTP", "status": "pass", "detail": "ok"}
            mock_ssl.return_value = {"check": "SSL", "status": "pass", "detail": "ok"}

            run_status(mock_cfg)

    @patch("lablink_cli.commands.status.estimate_costs")
    @patch("lablink_cli.commands.status.get_client_vms")
    @patch("lablink_cli.commands.status.get_terraform_outputs")
    @patch("lablink_cli.commands.status._get_deploy_dir")
    def test_with_stopped_vms(
        self, mock_deploy_dir, mock_outputs, mock_vms, mock_costs, mock_cfg, tmp_path
    ):
        mock_deploy_dir.return_value = tmp_path / "nonexistent"
        mock_vms.return_value = [
            {
                "name": "client-1",
                "instance_id": "i-1",
                "type": "g4dn.xlarge",
                "state": "running",
                "public_ip": "1.1.1.1",
            },
            {
                "name": "client-2",
                "instance_id": "i-2",
                "type": "g4dn.xlarge",
                "state": "stopped",
                "public_ip": None,
            },
            {
                "name": "client-3",
                "instance_id": "i-3",
                "type": "g4dn.xlarge",
                "state": "pending",
                "public_ip": None,
            },
        ]
        mock_costs.return_value = [
            {"resource": "EC2", "daily": 2.0, "note": "always on"}
        ]

        run_status(mock_cfg)
