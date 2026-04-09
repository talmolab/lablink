"""Tests for lablink_cli.commands.status health checks and cost estimation."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch


from lablink_cli.commands.status import (
    FALLBACK_COSTS,
    _build_health_url,
    _render_client_vms,
    _render_cost_estimate,
    _render_health_checks,
    _render_terraform_state,
    check_dns,
    check_health_endpoint,
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
# check_health_endpoint
# ------------------------------------------------------------------
class TestCheckHealthEndpoint:
    @patch("lablink_cli.commands.status.urlopen")
    def test_healthy(self, mock_urlopen):
        import json

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"status": "healthy", "checks": {"database": "ok"}, "uptime_seconds": 42.5}
        ).encode()
        mock_resp.getcode.return_value = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = check_health_endpoint("http://1.2.3.4:5000")
        assert result["status"] == "pass"
        assert result["healthy"] is True
        assert result["uptime_seconds"] == 42.5

    @patch("lablink_cli.commands.status.urlopen")
    def test_starting(self, mock_urlopen):
        import json
        from io import BytesIO
        from urllib.error import HTTPError

        body = json.dumps(
            {"status": "starting", "checks": {"database": "not initialized"}}
        ).encode()
        error = HTTPError(
            url="http://1.2.3.4:5000/api/health",
            code=503,
            msg="Service Unavailable",
            hdrs={},
            fp=BytesIO(body),
        )
        mock_urlopen.side_effect = error

        result = check_health_endpoint("http://1.2.3.4:5000")
        assert result["status"] == "starting"
        assert result["healthy"] is False

    @patch("lablink_cli.commands.status.urlopen")
    def test_connection_refused(self, mock_urlopen):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("connection refused")

        result = check_health_endpoint("http://1.2.3.4:5000")
        assert result["status"] == "unreachable"
        assert result["healthy"] is False


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


# ------------------------------------------------------------------
# _build_health_url
# ------------------------------------------------------------------
class TestBuildHealthUrl:
    def test_https_domain(self, mock_cfg):
        mock_cfg.dns.enabled = True
        mock_cfg.dns.domain = "test.example.com"
        mock_cfg.ssl.provider = "letsencrypt"
        outputs = {"ec2_public_ip": "1.2.3.4"}

        assert _build_health_url(mock_cfg, outputs) == "https://test.example.com"

    def test_http_domain(self, mock_cfg):
        mock_cfg.dns.enabled = True
        mock_cfg.dns.domain = "test.example.com"
        mock_cfg.ssl.provider = "none"
        outputs = {"ec2_public_ip": "1.2.3.4"}

        assert _build_health_url(mock_cfg, outputs) == "http://test.example.com"

    def test_ip_fallback(self, mock_cfg):
        mock_cfg.dns.enabled = False
        mock_cfg.dns.domain = ""
        mock_cfg.ssl.provider = "none"
        outputs = {"ec2_public_ip": "1.2.3.4"}

        assert _build_health_url(mock_cfg, outputs) == "http://1.2.3.4"

    def test_no_domain_no_ip(self, mock_cfg):
        mock_cfg.dns.enabled = False
        mock_cfg.dns.domain = ""
        mock_cfg.ssl.provider = "none"
        outputs = {}

        assert _build_health_url(mock_cfg, outputs) == ""


# ------------------------------------------------------------------
# _render_terraform_state
# ------------------------------------------------------------------
class TestRenderTerraformState:
    @patch("lablink_cli.commands.status.get_terraform_outputs")
    def test_returns_outputs(self, mock_outputs, tmp_path):
        mock_outputs.return_value = {
            "ec2_public_ip": "1.2.3.4",
            "ec2_key_name": "mykey",
        }
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()

        result = _render_terraform_state(deploy_dir)
        assert result["ec2_public_ip"] == "1.2.3.4"

    @patch("lablink_cli.commands.status.get_terraform_outputs")
    def test_no_deploy_dir(self, mock_outputs, tmp_path):
        deploy_dir = tmp_path / "nonexistent"
        result = _render_terraform_state(deploy_dir)
        assert result == {}
        mock_outputs.assert_not_called()

    @patch("lablink_cli.commands.status.get_terraform_outputs")
    def test_empty_outputs(self, mock_outputs, tmp_path):
        mock_outputs.return_value = {}
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()

        result = _render_terraform_state(deploy_dir)
        assert result == {}


# ------------------------------------------------------------------
# _render_health_checks
# ------------------------------------------------------------------
class TestRenderHealthChecks:
    @patch("lablink_cli.commands.status.check_ssl_cert")
    @patch("lablink_cli.commands.status.check_http")
    @patch("lablink_cli.commands.status.check_dns")
    def test_with_domain_and_ssl(
        self, mock_dns, mock_http, mock_ssl, mock_cfg
    ):
        mock_cfg.dns.enabled = True
        mock_cfg.dns.domain = "test.example.com"
        mock_cfg.ssl.provider = "letsencrypt"
        mock_dns.return_value = {
            "check": "DNS", "status": "pass", "detail": ""
        }
        mock_http.return_value = {
            "check": "HTTP", "status": "pass", "detail": ""
        }
        mock_ssl.return_value = {
            "check": "SSL", "status": "pass", "detail": ""
        }
        outputs = {"ec2_public_ip": "1.2.3.4"}

        _render_health_checks(mock_cfg, outputs)
        mock_dns.assert_called_once()
        mock_http.assert_called_once()
        mock_ssl.assert_called_once()

    def test_no_domain_no_ip(self, mock_cfg):
        mock_cfg.dns.enabled = False
        mock_cfg.dns.domain = ""
        mock_cfg.ssl.provider = "none"
        outputs = {}

        _render_health_checks(mock_cfg, outputs)


# ------------------------------------------------------------------
# _render_client_vms
# ------------------------------------------------------------------
class TestRenderClientVms:
    @patch("lablink_cli.commands.status.get_client_vms")
    def test_no_vms(self, mock_vms, mock_cfg):
        mock_vms.return_value = []
        _render_client_vms(mock_cfg)

    @patch("lablink_cli.commands.status.get_client_vms")
    def test_with_running_vms(self, mock_vms, mock_cfg):
        mock_vms.return_value = [
            {
                "name": "client-1",
                "instance_id": "i-123",
                "type": "g4dn.xlarge",
                "state": "running",
                "public_ip": "1.2.3.4",
            },
        ]
        _render_client_vms(mock_cfg)


# ------------------------------------------------------------------
# _render_cost_estimate
# ------------------------------------------------------------------
class TestRenderCostEstimate:
    @patch("lablink_cli.commands.status.estimate_costs")
    def test_renders_without_error(self, mock_costs, mock_cfg):
        mock_costs.return_value = [
            {"resource": "Allocator EC2", "daily": 2.0, "note": "always on"},
            {"resource": "Client VM", "daily": 12.6, "note": "per VM"},
        ]
        _render_cost_estimate(mock_cfg)
