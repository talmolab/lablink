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
    _render_tofu_state,
    check_dns,
    check_health_endpoint,
    check_http,
    estimate_costs,
)
from lablink_cli.docker import Docker, Result


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
# User-Agent header
#
# Cloudflare-proxied allocators return HTTP 403 to the default
# "Python-urllib/x.y" User-Agent. Health-check requests must send a
# product User-Agent so they reach the origin instead of being blocked
# at the Cloudflare edge.
# ------------------------------------------------------------------
class TestUserAgent:
    @patch("lablink_cli.commands.status.urlopen")
    def test_check_http_sends_product_user_agent(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_urlopen.return_value = mock_resp

        check_http("http://example.com")

        req = mock_urlopen.call_args.args[0]
        assert req.get_header("User-agent", "").startswith("lablink-cli/")

    @patch("lablink_cli.commands.status.urlopen")
    def test_check_health_endpoint_sends_product_user_agent(self, mock_urlopen):
        import json

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"status": "healthy"}).encode()
        mock_urlopen.return_value = mock_resp

        check_health_endpoint("http://1.2.3.4:5000")

        req = mock_urlopen.call_args.args[0]
        assert req.get_header("User-agent", "").startswith("lablink-cli/")


# ------------------------------------------------------------------
# estimate_costs
# ------------------------------------------------------------------
class TestEstimateCosts:
    def test_basic_costs(self, mock_cfg):
        mock_cfg.dns.enabled = False
        mock_cfg.ssl.provider = "none"

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

        with patch("lablink_cli.commands.status.boto3") as mock_boto:
            mock_boto.client.side_effect = Exception("no creds")
            costs = estimate_costs(mock_cfg)

        resource_names = [c["resource"] for c in costs]
        assert any("Route53" in r for r in resource_names)

    def test_acm_adds_alb(self, mock_cfg):
        mock_cfg.dns.enabled = True
        mock_cfg.ssl.provider = "acm"

        with patch("lablink_cli.commands.status.boto3") as mock_boto:
            mock_boto.client.side_effect = Exception("no creds")
            costs = estimate_costs(mock_cfg)

        resource_names = [c["resource"] for c in costs]
        assert any("Load Balancer" in r for r in resource_names)

    def test_client_vm_cost(self, mock_cfg):
        mock_cfg.dns.enabled = False
        mock_cfg.ssl.provider = "none"
        mock_cfg.machine.machine_type = "g4dn.xlarge"

        with patch("lablink_cli.commands.status.boto3") as mock_boto:
            mock_boto.client.side_effect = Exception("no creds")
            costs = estimate_costs(mock_cfg)

        resource_names = [c["resource"] for c in costs]
        assert any("Client VM" in r for r in resource_names)

    def test_all_costs_positive(self, mock_cfg):
        mock_cfg.dns.enabled = True
        mock_cfg.ssl.provider = "acm"

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
# _render_tofu_state
# ------------------------------------------------------------------
class TestRenderTofuState:
    @patch("lablink_cli.commands.status.get_tofu_outputs")
    def test_returns_outputs(self, mock_outputs, tmp_path):
        mock_outputs.return_value = {
            "ec2_public_ip": "1.2.3.4",
            "ec2_key_name": "mykey",
        }
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()

        result = _render_tofu_state(deploy_dir)
        assert result["ec2_public_ip"] == "1.2.3.4"

    @patch("lablink_cli.commands.status.get_tofu_outputs")
    def test_no_deploy_dir(self, mock_outputs, tmp_path):
        deploy_dir = tmp_path / "nonexistent"
        result = _render_tofu_state(deploy_dir)
        assert result == {}
        mock_outputs.assert_not_called()

    @patch("lablink_cli.commands.status.get_tofu_outputs")
    def test_empty_outputs(self, mock_outputs, tmp_path, capsys):
        mock_outputs.return_value = {}
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()

        result = _render_tofu_state(deploy_dir)
        assert result == {}
        assert "No OpenTofu state found" in capsys.readouterr().out

    @patch("lablink_cli.commands.status.get_tofu_outputs")
    def test_read_failure_with_dead_credentials_points_at_the_creds(
        self, mock_outputs, tmp_path, capsys
    ):
        """The credentials block printed above already carries the remedy,
        so repeating tofu's STS complaint here is noise."""
        from lablink_cli.commands.utils import TofuError

        mock_outputs.side_effect = TofuError("api error InvalidClientTokenId")
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()

        result = _render_tofu_state(deploy_dir, aws_unavailable=True)
        assert result == {}
        out = capsys.readouterr().out
        assert "see AWS credentials above" in out
        assert "No OpenTofu state found" not in out

    @patch("lablink_cli.commands.status.get_tofu_outputs")
    def test_error_containing_rich_markup_does_not_abort(
        self, mock_outputs, tmp_path, capsys
    ):
        """tofu names files in brackets, and `[/var/...]` reads to Rich as a
        closing tag with no opening tag — which raises MarkupError and kills
        the command that was trying to report the problem."""
        from lablink_cli.commands.utils import TofuError

        mock_outputs.side_effect = TofuError(
            "Error: cannot read [/var/lib/state] here"
        )
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()

        result = _render_tofu_state(deploy_dir)

        assert result == {}
        assert "[/var/lib/state]" in capsys.readouterr().out

    @patch("lablink_cli.commands.status.get_tofu_outputs")
    def test_read_failure_without_creds_problem_shows_the_reason(
        self, mock_outputs, tmp_path, capsys
    ):
        """A non-auth failure (held lock, uninitialised backend) has no
        block above it, so the reason has to be printed here rather than
        reported as an absent deployment."""
        from lablink_cli.commands.utils import TofuError

        mock_outputs.side_effect = TofuError("Error acquiring the state lock")
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()

        result = _render_tofu_state(deploy_dir)
        assert result == {}
        out = capsys.readouterr().out
        assert "Error acquiring the state lock" in out
        assert "No OpenTofu state found" not in out


# ------------------------------------------------------------------
# _render_health_checks
# ------------------------------------------------------------------
class TestRenderHealthChecks:
    @patch("lablink_cli.commands.status.check_ssl_cert")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    @patch("lablink_cli.commands.status.check_dns")
    def test_with_domain_and_ssl(
        self, mock_dns, mock_health, mock_ssl, mock_cfg
    ):
        mock_cfg.dns.enabled = True
        mock_cfg.dns.domain = "test.example.com"
        mock_cfg.ssl.provider = "letsencrypt"
        mock_dns.return_value = {
            "check": "DNS", "status": "pass", "detail": ""
        }
        mock_health.return_value = {
            "status": "pass",
            "healthy": True,
            "uptime_seconds": 42.0,
            "detail": "healthy",
        }
        mock_ssl.return_value = {
            "check": "SSL", "status": "pass", "detail": ""
        }
        outputs = {"ec2_public_ip": "1.2.3.4"}

        _render_health_checks(mock_cfg, outputs)
        mock_dns.assert_called_once()
        mock_health.assert_called_once()
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

    @patch("lablink_cli.commands.status.get_client_vms")
    def test_auth_failure_is_not_reported_as_empty(
        self, mock_vms, mock_cfg, capsys
    ):
        """A failed EC2 query must never read as "no VMs exist"."""
        from lablink_cli.commands.utils import AwsQueryError

        mock_vms.side_effect = AwsQueryError(
            "No AWS credentials found", is_auth=True
        )

        _render_client_vms(mock_cfg)

        out = capsys.readouterr().out
        assert "No client VMs found" not in out
        assert "No AWS credentials found" in out
        # Auth failures get remediation; other API errors don't.
        assert "aws configure" in out

    @patch("lablink_cli.commands.status.get_client_vms")
    def test_permission_failure_gets_iam_guidance(
        self, mock_vms, mock_cfg, capsys
    ):
        """Valid credentials without ec2:DescribeInstances is the case the
        upfront STS probe cannot catch, and 'aws configure' cannot fix."""
        from lablink_cli.commands.utils import AwsQueryError

        mock_vms.side_effect = AwsQueryError(
            "AWS denied the request: UnauthorizedOperation — not "
            "authorized to perform ec2:DescribeInstances",
            is_permission=True,
        )

        _render_client_vms(mock_cfg)

        out = capsys.readouterr().out
        assert "No client VMs found" not in out
        assert "ec2:DescribeInstances" in out
        assert "lack permission" in out
        assert "aws configure" not in out

    @patch("lablink_cli.commands.status.get_client_vms")
    def test_non_auth_query_failure_is_surfaced(
        self, mock_vms, mock_cfg, capsys
    ):
        from lablink_cli.commands.utils import AwsQueryError

        mock_vms.side_effect = AwsQueryError(
            "ThrottlingException: slow down", is_auth=False
        )

        _render_client_vms(mock_cfg)

        out = capsys.readouterr().out
        assert "No client VMs found" not in out
        assert "ThrottlingException" in out
        assert "aws configure" not in out


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


# ------------------------------------------------------------------
# Manual-provider status
# ------------------------------------------------------------------
class _ComposeDocker(Docker):
    """Answers `compose(workdir, "ps")` with a fixed Result."""

    def __init__(self, result=Result(0)):
        self._result = result
        self.calls = []

    def available(self):
        return True

    def require(self):
        return None

    def compose(self, workdir, *args, capture=True):
        self.calls.append((workdir, args, capture))
        return self._result


class TestManualStatus:
    @patch("lablink_cli.commands.status.default_docker")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    def test_manual_reports_compose_health(
        self, mock_health, mock_default_docker, capsys, mock_cfg, tmp_path,
    ):
        from lablink_cli.commands.status import run_status

        mock_cfg.provider = "manual"
        mock_cfg.deployment_name = "testlab"
        # Create the compose workdir so the function proceeds past the
        # "no compose stack" branch.
        workdir = tmp_path / ".lablink" / "compose" / "testlab"
        workdir.mkdir(parents=True)
        mock_default_docker.return_value = _ComposeDocker(
            Result(0, stdout="NAME              STATUS\nlablink-allocator running")
        )
        mock_health.return_value = {"healthy": True, "detail": ""}

        with patch("lablink_cli.commands.status.Path.home", return_value=tmp_path):
            run_status(mock_cfg)

        out = capsys.readouterr().out
        assert "allocator" in out.lower()

    @patch("lablink_cli.commands.status.default_docker")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    def test_manual_no_compose_stack(
        self, mock_health, mock_default_docker, capsys, mock_cfg, tmp_path,
    ):
        from lablink_cli.commands.status import run_status

        mock_cfg.provider = "manual"
        mock_cfg.deployment_name = "missing-lab"
        fake_docker = _ComposeDocker()
        mock_default_docker.return_value = fake_docker

        with patch("lablink_cli.commands.status.Path.home", return_value=tmp_path):
            run_status(mock_cfg)

        out = capsys.readouterr().out
        assert "No compose stack" in out
        assert fake_docker.calls == []
        mock_health.assert_not_called()

    @patch("lablink_cli.commands.status.default_docker")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    def test_manual_allocator_unhealthy(
        self, mock_health, mock_default_docker, capsys, mock_cfg, tmp_path,
    ):
        from lablink_cli.commands.status import run_status

        mock_cfg.provider = "manual"
        mock_cfg.deployment_name = "testlab"
        workdir = tmp_path / ".lablink" / "compose" / "testlab"
        workdir.mkdir(parents=True)
        mock_default_docker.return_value = _ComposeDocker(Result(0, stdout=""))
        mock_health.return_value = {"healthy": False, "detail": "starting"}

        with patch("lablink_cli.commands.status.Path.home", return_value=tmp_path):
            run_status(mock_cfg)

        out = capsys.readouterr().out
        assert "not healthy" in out.lower()

    @patch("lablink_cli.commands.status.default_docker")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    def test_manual_self_signed_uses_https(
        self, mock_health, mock_default_docker, mock_cfg, tmp_path,
    ):
        from lablink_cli.commands.status import run_status

        mock_cfg.provider = "manual"
        mock_cfg.deployment_name = "testlab"
        mock_cfg.ssl.provider = "self_signed"
        workdir = tmp_path / ".lablink" / "compose" / "testlab"
        workdir.mkdir(parents=True)
        mock_default_docker.return_value = _ComposeDocker(Result(0, stdout=""))
        mock_health.return_value = {"healthy": True, "detail": ""}

        with patch("lablink_cli.commands.status.Path.home", return_value=tmp_path):
            run_status(mock_cfg)

        # Health URL should use https scheme for self_signed.
        called_url = mock_health.call_args[0][0]
        assert called_url.startswith("https://")


class TestManualStatusPublicUrl:
    """`lablink status` must surface the participant-facing URL, not just the
    localhost liveness probe — on a Funnel deployment localhost is not an
    address any participant or BYO client can use."""

    @staticmethod
    def _workdir(tmp_path, url=None):
        wd = tmp_path / ".lablink" / "compose" / "testlab"
        wd.mkdir(parents=True)
        if url is not None:
            (wd / "allocator-url").write_text(url)
        return wd

    @patch("lablink_cli.commands.status.default_docker")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    def test_shows_funnel_url_and_checks_it(
        self, mock_health, mock_default_docker, capsys, mock_cfg, tmp_path,
    ):
        from lablink_cli.commands.status import run_status

        mock_cfg.provider = "manual"
        mock_cfg.deployment_name = "testlab"
        mock_cfg.manual.participant_exposure = "tailscale_funnel"
        self._workdir(tmp_path, "https://lablink-allocator-testlab.example.ts.net\n")
        mock_default_docker.return_value = _ComposeDocker(Result(0, stdout=""))
        mock_health.return_value = {"healthy": True, "detail": ""}

        with patch("lablink_cli.commands.status.Path.home", return_value=tmp_path):
            run_status(mock_cfg)

        out = capsys.readouterr().out
        assert "https://lablink-allocator-testlab.example.ts.net" in out
        assert "Tailscale Funnel" in out
        # Probed in addition to localhost, not instead of it.
        probed = [c.args[0] for c in mock_health.call_args_list]
        assert "https://lablink-allocator-testlab.example.ts.net" in probed
        assert any("localhost" in p for p in probed)

    @patch("lablink_cli.commands.status.default_docker")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    def test_reports_unreachable_funnel_url(
        self, mock_health, mock_default_docker, capsys, mock_cfg, tmp_path,
    ):
        """A dead Funnel is invisible to a localhost probe — the whole reason
        to check the public URL separately."""
        from lablink_cli.commands.status import run_status

        mock_cfg.provider = "manual"
        mock_cfg.deployment_name = "testlab"
        mock_cfg.manual.participant_exposure = "tailscale_funnel"
        self._workdir(tmp_path, "https://lablink-allocator-testlab.example.ts.net")
        mock_default_docker.return_value = _ComposeDocker(Result(0, stdout=""))
        mock_health.side_effect = [
            {"healthy": True, "detail": ""},                      # localhost
            {"healthy": False, "detail": "connection refused"},   # funnel
        ]

        with patch("lablink_cli.commands.status.Path.home", return_value=tmp_path):
            run_status(mock_cfg)

        out = capsys.readouterr().out
        assert "Not reachable" in out
        assert "connection refused" in out

    @patch("lablink_cli.commands.status.default_docker")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    def test_no_public_url_line_when_not_exposed(
        self, mock_health, mock_default_docker, capsys, mock_cfg, tmp_path,
    ):
        """Non-Funnel deployments stage the file empty; nothing extra printed
        and no second probe fired."""
        from lablink_cli.commands.status import run_status

        mock_cfg.provider = "manual"
        mock_cfg.deployment_name = "testlab"
        mock_cfg.manual.participant_exposure = "none"
        self._workdir(tmp_path, "")
        mock_default_docker.return_value = _ComposeDocker(Result(0, stdout=""))
        mock_health.return_value = {"healthy": True, "detail": ""}

        with patch("lablink_cli.commands.status.Path.home", return_value=tmp_path):
            run_status(mock_cfg)

        assert "Public URL" not in capsys.readouterr().out
        assert mock_health.call_count == 1

    @patch("lablink_cli.commands.status.default_docker")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    def test_missing_file_is_not_an_error(
        self, mock_health, mock_default_docker, capsys, mock_cfg, tmp_path,
    ):
        """A deployment dir rendered by an older CLI has no such file."""
        from lablink_cli.commands.status import run_status

        mock_cfg.provider = "manual"
        mock_cfg.deployment_name = "testlab"
        mock_cfg.manual.participant_exposure = "none"
        self._workdir(tmp_path, None)
        mock_default_docker.return_value = _ComposeDocker(Result(0, stdout=""))
        mock_health.return_value = {"healthy": True, "detail": ""}

        with patch("lablink_cli.commands.status.Path.home", return_value=tmp_path):
            run_status(mock_cfg)

        assert "Public URL" not in capsys.readouterr().out
