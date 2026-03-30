"""Tests for lablink_cli.commands.status health checks and cost estimation."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch


from lablink_cli.commands.status import (
    FALLBACK_COSTS,
    check_dns,
    check_http,
    estimate_costs,
)


# ------------------------------------------------------------------
# check_dns
# ------------------------------------------------------------------
class TestCheckDns:
    def test_no_domain(self):
        result = check_dns("", "1.2.3.4")
        assert result["status"] == "skip"

    @patch("socket.gethostbyname", return_value="1.2.3.4")
    def test_correct_resolution(self, _mock):
        result = check_dns("test.example.com", "1.2.3.4")
        assert result["status"] == "pass"

    @patch("socket.gethostbyname", return_value="5.6.7.8")
    def test_wrong_ip(self, _mock):
        result = check_dns("test.example.com", "1.2.3.4")
        assert result["status"] == "warn"
        assert "expected" in result["detail"]

    @patch("socket.gethostbyname", side_effect=socket.gaierror("nope"))
    def test_dns_failure(self, _mock):
        result = check_dns("test.example.com", "1.2.3.4")
        assert result["status"] == "fail"


# ------------------------------------------------------------------
# check_http
# ------------------------------------------------------------------
class TestCheckHttp:
    @patch("lablink_cli.commands.status.urlopen")
    def test_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_urlopen.return_value = mock_resp

        result = check_http("http://example.com")
        assert result["status"] == "pass"
        assert "200" in result["detail"]

    @patch("lablink_cli.commands.status.urlopen")
    def test_error_code(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 500
        mock_urlopen.return_value = mock_resp

        result = check_http("http://example.com")
        assert result["status"] == "warn"

    @patch("lablink_cli.commands.status.urlopen")
    def test_connection_error(self, mock_urlopen):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("connection refused")

        result = check_http("http://example.com")
        assert result["status"] == "fail"


# ------------------------------------------------------------------
# estimate_costs
# ------------------------------------------------------------------
class TestEstimateCosts:
    def test_basic_costs(self, mock_cfg):
        mock_cfg.dns.enabled = False
        mock_cfg.ssl.provider = "none"
        mock_cfg.monitoring.enabled = False

        with patch("lablink_cli.commands.status.boto3") as mock_boto:
            mock_boto.client.side_effect = Exception("no creds")
            costs = estimate_costs(mock_cfg)

        # Should have allocator EC2, EBS, EIP at minimum
        resource_names = [c["resource"] for c in costs]
        assert any("Allocator EC2" in r for r in resource_names)
        assert any("EBS" in r for r in resource_names)
        assert any("Elastic IP" in r for r in resource_names)

    def test_dns_adds_route53(self, mock_cfg):
        mock_cfg.dns.enabled = True
        mock_cfg.ssl.provider = "none"
        mock_cfg.monitoring.enabled = False

        with patch("lablink_cli.commands.status.boto3") as mock_boto:
            mock_boto.client.side_effect = Exception("no creds")
            costs = estimate_costs(mock_cfg)

        resource_names = [c["resource"] for c in costs]
        assert any("Route53" in r for r in resource_names)

    def test_acm_adds_alb(self, mock_cfg):
        mock_cfg.dns.enabled = True
        mock_cfg.ssl.provider = "acm"
        mock_cfg.monitoring.enabled = False

        with patch("lablink_cli.commands.status.boto3") as mock_boto:
            mock_boto.client.side_effect = Exception("no creds")
            costs = estimate_costs(mock_cfg)

        resource_names = [c["resource"] for c in costs]
        assert any("Load Balancer" in r for r in resource_names)

    def test_monitoring_adds_cloudwatch(self, mock_cfg):
        mock_cfg.dns.enabled = False
        mock_cfg.ssl.provider = "none"
        mock_cfg.monitoring.enabled = True

        with patch("lablink_cli.commands.status.boto3") as mock_boto:
            mock_boto.client.side_effect = Exception("no creds")
            costs = estimate_costs(mock_cfg)

        resource_names = [c["resource"] for c in costs]
        assert any("CloudWatch" in r for r in resource_names)
        assert any("CloudTrail" in r for r in resource_names)

    def test_client_vm_cost(self, mock_cfg):
        mock_cfg.dns.enabled = False
        mock_cfg.ssl.provider = "none"
        mock_cfg.monitoring.enabled = False
        mock_cfg.machine.machine_type = "g4dn.xlarge"

        with patch("lablink_cli.commands.status.boto3") as mock_boto:
            mock_boto.client.side_effect = Exception("no creds")
            costs = estimate_costs(mock_cfg)

        resource_names = [c["resource"] for c in costs]
        assert any("Client VM" in r for r in resource_names)

    def test_all_costs_positive(self, mock_cfg):
        mock_cfg.dns.enabled = True
        mock_cfg.ssl.provider = "acm"
        mock_cfg.monitoring.enabled = True

        with patch("lablink_cli.commands.status.boto3") as mock_boto:
            mock_boto.client.side_effect = Exception("no creds")
            costs = estimate_costs(mock_cfg)

        for c in costs:
            assert c["daily"] > 0, f"{c['resource']} has non-positive cost"


# ------------------------------------------------------------------
# FALLBACK_COSTS reference data
# ------------------------------------------------------------------
class TestFallbackCosts:
    def test_ec2_costs_exist(self):
        assert "ec2" in FALLBACK_COSTS
        assert len(FALLBACK_COSTS["ec2"]) > 0

    def test_all_ec2_costs_positive(self):
        for itype, cost in FALLBACK_COSTS["ec2"].items():
            assert cost > 0, f"{itype} cost should be positive"
