"""Tests for lablink_cli.commands.status run_status and additional helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lablink_cli.commands.status import (
    REGION_NAME_MAP,
    _get_ec2_price,
    _render_aws_credentials_error,
    run_status,
)
from lablink_cli.commands.utils import AwsQueryError


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
    @pytest.fixture(autouse=True)
    def _valid_aws_credentials(self):
        """Keep run_status offline: the credential probe is a real STS call.

        Tests that exercise the failure path patch over this.
        """
        with patch(
            "lablink_cli.commands.status.aws_credentials_error",
            return_value=None,
        ):
            yield

    @patch("lablink_cli.commands.status.estimate_costs")
    @patch("lablink_cli.commands.status.get_client_vms")
    @patch("lablink_cli.commands.status.get_tofu_outputs")
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
    @patch("lablink_cli.commands.status.get_tofu_outputs")
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
    @patch("lablink_cli.commands.status.get_tofu_outputs")
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
    @patch("lablink_cli.commands.status.get_tofu_outputs")
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


# ------------------------------------------------------------------
# run_status when AWS credentials are missing / expired
# ------------------------------------------------------------------
class TestRunStatusAwsCredentialsFailure:
    """The reported bug: status reported "No client VMs found" and a cost
    table as if healthy, while the real problem was an unauthenticated
    caller."""

    def _run(self, mock_cfg, tmp_path, err, vms_side_effect=None):
        with patch(
            "lablink_cli.commands.status.aws_credentials_error",
            return_value=err,
        ), patch(
            "lablink_cli.commands.status._get_deploy_dir",
            return_value=tmp_path / "nonexistent",
        ), patch(
            "lablink_cli.commands.status.get_client_vms"
        ) as mock_vms, patch(
            "lablink_cli.commands.status.check_health_endpoint"
        ) as mock_health, patch(
            "lablink_cli.commands.status.estimate_costs"
        ) as mock_costs:
            mock_vms.return_value = []
            if vms_side_effect is not None:
                mock_vms.side_effect = vms_side_effect
            mock_health.return_value = {
                "healthy": True,
                "status": "pass",
                "detail": "ok",
                "uptime_seconds": None,
            }
            mock_costs.return_value = [
                {"resource": "EC2", "daily": 2.0, "note": "always on"}
            ]
            mock_cfg.dns.enabled = True
            mock_cfg.dns.domain = "test.example.com"
            mock_cfg.ssl.provider = "none"

            with patch("lablink_cli.commands.status.check_dns") as mock_dns:
                mock_dns.return_value = {
                    "check": "DNS", "status": "pass", "detail": "ok",
                }
                run_status(mock_cfg)

            return mock_vms, mock_health, mock_costs

    def test_reports_credential_failure_instead_of_empty_inventory(
        self, mock_cfg, tmp_path, capsys
    ):
        err = AwsQueryError(
            "AWS credentials are expired (ExpiredToken)", is_auth=True
        )
        mock_vms, _, _ = self._run(mock_cfg, tmp_path, err)

        out = capsys.readouterr().out
        assert "ExpiredToken" in out
        assert "aws configure" in out
        # The two lies from the bug report must be gone.
        assert "No client VMs found" not in out
        assert "No OpenTofu state found" not in out
        # And we must not waste a doomed EC2 round-trip.
        mock_vms.assert_not_called()

    def test_still_runs_network_health_checks(
        self, mock_cfg, tmp_path, capsys
    ):
        """DNS/HTTP/SSL need no AWS credentials, so they stay useful."""
        err = AwsQueryError("No AWS credentials found", is_auth=True)
        _, mock_health, _ = self._run(mock_cfg, tmp_path, err)

        mock_health.assert_called_once()
        assert "Health Checks" in capsys.readouterr().out

    def test_costs_marked_as_fallback(self, mock_cfg, tmp_path, capsys):
        err = AwsQueryError("No AWS credentials found", is_auth=True)
        _, _, mock_costs = self._run(mock_cfg, tmp_path, err)

        out = capsys.readouterr().out
        assert "fallback" in out.lower()
        # Don't attempt the AWS Pricing API we know will fail.
        assert mock_costs.call_args.kwargs.get("use_pricing_api") is False

    def test_non_auth_probe_failure_omits_credential_remedy(
        self, mock_cfg, tmp_path, capsys
    ):
        err = AwsQueryError("Could not connect to STS endpoint", is_auth=False)
        self._run(mock_cfg, tmp_path, err)

        out = capsys.readouterr().out
        assert "Could not connect to STS endpoint" in out
        assert "aws configure" not in out

    def test_non_auth_probe_failure_still_queries_ec2(
        self, mock_cfg, tmp_path, capsys
    ):
        """A failed STS probe does not prove EC2 is unreachable.

        STS can be blocked by a proxy or VPC endpoint policy while EC2
        answers fine, so a non-credential probe failure must not skip the
        inventory the way an auth failure does.
        """
        err = AwsQueryError("Could not connect to STS endpoint", is_auth=False)
        mock_vms, _, mock_costs = self._run(mock_cfg, tmp_path, err)

        mock_vms.assert_called_once()
        # Pricing is only doomed when credentials are the problem.
        assert mock_costs.call_args.kwargs.get("use_pricing_api") is True
        out = capsys.readouterr().out
        assert "Inventory unavailable" not in out
        # The query succeeded and matched nothing — say so honestly.
        assert "No client VMs found" in out

    def test_non_auth_probe_then_failing_ec2_query_reports_the_query_error(
        self, mock_cfg, tmp_path, capsys
    ):
        """The _render_client_vms except branch must stay reachable.

        Gating the skip on "any probe failure" made this path dead: the
        inventory was skipped before the query could report for itself.
        """
        probe_err = AwsQueryError("STS endpoint unreachable", is_auth=False)
        query_err = AwsQueryError(
            "AWS rejected the request: AuthFailure — bad creds", is_auth=True
        )
        mock_vms, _, _ = self._run(
            mock_cfg, tmp_path, probe_err, vms_side_effect=query_err
        )

        mock_vms.assert_called_once()
        out = capsys.readouterr().out
        assert "Could not query EC2" in out
        assert "AuthFailure" in out
        assert "No client VMs found" not in out


# ------------------------------------------------------------------
# _render_aws_credentials_error — which profile is being blamed
# ------------------------------------------------------------------
class TestRenderAwsCredentialsError:
    def test_unset_profile_reads_as_default(self, monkeypatch, capsys):
        monkeypatch.delenv("AWS_PROFILE", raising=False)
        _render_aws_credentials_error(
            AwsQueryError("No usable AWS credentials found", is_auth=True),
            "us-west-2",
        )
        out = capsys.readouterr().out
        assert "profile: default" in out
        assert "us-west-2" in out

    def test_named_profile_is_reported(self, monkeypatch, capsys):
        monkeypatch.setenv("AWS_PROFILE", "salk-research")
        _render_aws_credentials_error(
            AwsQueryError("AWS SSO session is not usable", is_auth=True),
            "us-east-1",
        )
        assert "profile: salk-research" in capsys.readouterr().out

    def test_empty_profile_is_called_out(self, monkeypatch, capsys):
        """An exported-but-empty AWS_PROFILE breaks every AWS call, so
        reporting it as "default" would contradict the error above it."""
        monkeypatch.setenv("AWS_PROFILE", "")
        _render_aws_credentials_error(
            AwsQueryError("AWS profile not found", is_auth=True),
            "us-east-1",
        )
        out = capsys.readouterr().out
        assert "set but empty" in out
        assert "profile: default" not in out
