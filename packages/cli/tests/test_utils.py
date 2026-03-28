"""Tests for lablink_cli.commands.utils EC2 and terraform helpers."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from lablink_cli.commands.utils import (
    _parse_instances,
    get_terraform_outputs,
    query_ec2_instances,
    get_allocator_vm,
    get_client_vms,
    list_all_vms,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
def _make_ec2_response(instances: list[dict]) -> dict:
    """Build a minimal EC2 describe_instances response."""
    return {
        "Reservations": [{"Instances": instances}],
    }


def _make_instance(
    name: str = "test-vm",
    instance_id: str = "i-abc123",
    instance_type: str = "g4dn.xlarge",
    state: str = "running",
    public_ip: str | None = "1.2.3.4",
    launch_time: str = "2025-01-01T00:00:00Z",
) -> dict:
    inst = {
        "InstanceId": instance_id,
        "InstanceType": instance_type,
        "State": {"Name": state},
        "Tags": [{"Key": "Name", "Value": name}],
        "LaunchTime": launch_time,
    }
    if public_ip:
        inst["PublicIpAddress"] = public_ip
    return inst


@pytest.fixture()
def mock_cfg():
    """Minimal Config-like object for testing."""
    cfg = MagicMock()
    cfg.app.region = "us-east-1"
    cfg.deployment_name = "mylab"
    cfg.environment = "dev"
    cfg.machine.software = "sleap"
    cfg.dns.enabled = False
    cfg.dns.domain = ""
    cfg.ssl.provider = "none"
    return cfg


# ------------------------------------------------------------------
# _parse_instances
# ------------------------------------------------------------------
class TestParseInstances:
    def test_empty_response(self):
        assert _parse_instances({}) == []

    def test_empty_reservations(self):
        assert _parse_instances({"Reservations": []}) == []

    def test_single_instance(self):
        resp = _make_ec2_response([_make_instance(name="vm-1")])
        result = _parse_instances(resp)
        assert len(result) == 1
        assert result[0]["name"] == "vm-1"
        assert result[0]["instance_id"] == "i-abc123"
        assert result[0]["type"] == "g4dn.xlarge"
        assert result[0]["state"] == "running"
        assert result[0]["public_ip"] == "1.2.3.4"

    def test_multiple_instances(self):
        resp = _make_ec2_response([
            _make_instance(name="vm-1", instance_id="i-1"),
            _make_instance(name="vm-2", instance_id="i-2"),
        ])
        result = _parse_instances(resp)
        assert len(result) == 2
        assert result[0]["name"] == "vm-1"
        assert result[1]["name"] == "vm-2"

    def test_no_public_ip(self):
        resp = _make_ec2_response([
            _make_instance(name="vm-1", public_ip=None),
        ])
        result = _parse_instances(resp)
        assert result[0]["public_ip"] == "\u2014"

    def test_no_name_tag(self):
        inst = _make_instance()
        inst["Tags"] = [{"Key": "Environment", "Value": "dev"}]
        resp = _make_ec2_response([inst])
        result = _parse_instances(resp)
        assert result[0]["name"] == ""

    def test_multiple_reservations(self):
        resp = {
            "Reservations": [
                {"Instances": [_make_instance(name="vm-1", instance_id="i-1")]},
                {"Instances": [_make_instance(name="vm-2", instance_id="i-2")]},
            ]
        }
        result = _parse_instances(resp)
        assert len(result) == 2


# ------------------------------------------------------------------
# query_ec2_instances
# ------------------------------------------------------------------
class TestQueryEc2Instances:
    @patch("lablink_cli.commands.utils._get_session", create=True)
    def test_returns_instances(self, mock_get_session):
        mock_ec2 = MagicMock()
        mock_get_session.return_value.client.return_value = mock_ec2
        mock_ec2.describe_instances.return_value = _make_ec2_response([
            _make_instance(name="vm-1"),
        ])

        with patch(
            "lablink_cli.commands.setup._get_session", mock_get_session
        ):
            result = query_ec2_instances("us-east-1", "my-tag-*")

        assert len(result) == 1
        assert result[0]["name"] == "vm-1"
        mock_ec2.describe_instances.assert_called_once_with(
            Filters=[
                {"Name": "tag:Name", "Values": ["my-tag-*"]},
                {"Name": "instance-state-name", "Values": ["running"]},
            ]
        )

    @patch("lablink_cli.commands.utils._get_session", create=True)
    def test_custom_states(self, mock_get_session):
        mock_ec2 = MagicMock()
        mock_get_session.return_value.client.return_value = mock_ec2
        mock_ec2.describe_instances.return_value = _make_ec2_response([])

        with patch(
            "lablink_cli.commands.setup._get_session", mock_get_session
        ):
            query_ec2_instances(
                "us-east-1", "tag", states=["running", "stopped"]
            )

        call_args = mock_ec2.describe_instances.call_args
        state_filter = call_args[1]["Filters"][1]
        assert state_filter["Values"] == ["running", "stopped"]

    @patch("lablink_cli.commands.utils._get_session", create=True)
    def test_session_error_returns_empty(self, mock_get_session):
        mock_get_session.side_effect = Exception("no credentials")

        with patch(
            "lablink_cli.commands.setup._get_session", mock_get_session
        ):
            result = query_ec2_instances("us-east-1", "tag")

        assert result == []

    @patch("lablink_cli.commands.utils._get_session", create=True)
    def test_describe_error_returns_empty(self, mock_get_session):
        mock_ec2 = MagicMock()
        mock_get_session.return_value.client.return_value = mock_ec2
        mock_ec2.describe_instances.side_effect = Exception("API error")

        with patch(
            "lablink_cli.commands.setup._get_session", mock_get_session
        ):
            result = query_ec2_instances("us-east-1", "tag")

        assert result == []


# ------------------------------------------------------------------
# get_allocator_vm / get_client_vms / list_all_vms
# ------------------------------------------------------------------
class TestVmHelpers:
    @patch("lablink_cli.commands.utils.query_ec2_instances")
    def test_get_allocator_vm_found(self, mock_query, mock_cfg):
        mock_query.return_value = [
            {"name": "mylab-allocator-dev", "instance_id": "i-alloc"}
        ]
        result = get_allocator_vm(mock_cfg)
        assert result["vm_type"] == "allocator"
        assert result["instance_id"] == "i-alloc"
        mock_query.assert_called_once_with(
            "us-east-1", "mylab-allocator-dev"
        )

    @patch("lablink_cli.commands.utils.query_ec2_instances")
    def test_get_allocator_vm_not_found(self, mock_query, mock_cfg):
        mock_query.return_value = []
        assert get_allocator_vm(mock_cfg) is None

    @patch("lablink_cli.commands.utils.query_ec2_instances")
    def test_get_client_vms(self, mock_query, mock_cfg):
        mock_query.return_value = [
            {"name": "sleap-lablink-client-dev-vm-1"},
            {"name": "sleap-lablink-client-dev-vm-2"},
        ]
        result = get_client_vms(mock_cfg)
        assert len(result) == 2
        assert all(vm["vm_type"] == "client" for vm in result)
        mock_query.assert_called_once_with(
            "us-east-1",
            "sleap-lablink-client-dev-vm-*",
            states=["running", "stopped", "pending"],
        )

    @patch("lablink_cli.commands.utils.get_client_vms")
    @patch("lablink_cli.commands.utils.get_allocator_vm")
    def test_list_all_vms(self, mock_alloc, mock_clients, mock_cfg):
        mock_alloc.return_value = {"name": "allocator", "vm_type": "allocator"}
        mock_clients.return_value = [
            {"name": "client-1", "vm_type": "client"},
        ]
        result = list_all_vms(mock_cfg)
        assert len(result) == 2
        assert result[0]["vm_type"] == "allocator"
        assert result[1]["vm_type"] == "client"

    @patch("lablink_cli.commands.utils.get_client_vms")
    @patch("lablink_cli.commands.utils.get_allocator_vm")
    def test_list_all_vms_no_allocator(self, mock_alloc, mock_clients, mock_cfg):
        mock_alloc.return_value = None
        mock_clients.return_value = [
            {"name": "client-1", "vm_type": "client"},
        ]
        result = list_all_vms(mock_cfg)
        assert len(result) == 1
        assert result[0]["vm_type"] == "client"


# ------------------------------------------------------------------
# get_terraform_outputs
# ------------------------------------------------------------------
class TestGetTerraformOutputs:
    def test_valid_output(self, tmp_path):
        tf_output = json.dumps({
            "ec2_public_ip": {"value": "10.0.0.1"},
            "private_key_pem": {"value": "-----BEGIN RSA PRIVATE KEY-----"},
        })
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=tf_output, returncode=0)
            result = get_terraform_outputs(tmp_path)

        assert result == {
            "ec2_public_ip": "10.0.0.1",
            "private_key_pem": "-----BEGIN RSA PRIVATE KEY-----",
        }
        mock_run.assert_called_once_with(
            ["terraform", "output", "-json"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )

    def test_subprocess_error(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "terraform")
            result = get_terraform_outputs(tmp_path)

        assert result == {}

    def test_invalid_json(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="not json", returncode=0)
            result = get_terraform_outputs(tmp_path)

        assert result == {}

    def test_empty_output(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="{}", returncode=0)
            result = get_terraform_outputs(tmp_path)

        assert result == {}
