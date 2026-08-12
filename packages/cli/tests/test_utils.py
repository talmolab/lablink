"""Tests for lablink_cli.commands.utils EC2 and tofu helpers."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import (
    ClientError,
    NoCredentialsError,
    ProfileNotFound,
    TokenRetrievalError,
)

from lablink_cli.commands.utils import (
    AwsQueryError,
    _classify_aws_error,
    _parse_instances,
    aws_credentials_error,
    get_tofu_outputs,
    TofuError,
    print_aws_error,
    query_ec2_instances,
    get_allocator_vm,
    get_client_vms,
    list_all_vms,
    summarize_tofu,
)


class TestSummarizeTofu:
    def test_matches_apply_summary(self):
        output = "Apply complete! Resources: 3 added, 0 changed, 0 destroyed."
        assert summarize_tofu(output) == (
            "Resources: 3 added, 0 changed, 0 destroyed"
        )

    def test_matches_destroy_summary(self):
        output = "Destroy complete! Resources: 7 destroyed."
        assert summarize_tofu(output) == "Resources: 7 destroyed"

    def test_returns_none_when_no_summary(self):
        assert summarize_tofu("tofu init\nno summary here") is None


def _client_error(code: str) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": f"{code} message"}},
        "DescribeInstances",
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
    def test_session_error_raises_auth_error(self, mock_get_session):
        """A credential failure must not masquerade as "no instances"."""
        mock_get_session.side_effect = NoCredentialsError()

        with patch(
            "lablink_cli.commands.setup._get_session", mock_get_session
        ):
            with pytest.raises(AwsQueryError) as exc:
                query_ec2_instances("us-east-1", "tag")

        assert exc.value.is_auth is True

    @patch("lablink_cli.commands.utils._get_session", create=True)
    def test_describe_auth_error_raises_auth_error(self, mock_get_session):
        mock_ec2 = MagicMock()
        mock_get_session.return_value.client.return_value = mock_ec2
        mock_ec2.describe_instances.side_effect = _client_error("AuthFailure")

        with patch(
            "lablink_cli.commands.setup._get_session", mock_get_session
        ):
            with pytest.raises(AwsQueryError) as exc:
                query_ec2_instances("us-east-1", "tag")

        assert exc.value.is_auth is True

    @patch("lablink_cli.commands.utils._get_session", create=True)
    def test_describe_other_error_raises_non_auth(self, mock_get_session):
        """Non-credential API failures still surface, just not as auth."""
        mock_ec2 = MagicMock()
        mock_get_session.return_value.client.return_value = mock_ec2
        mock_ec2.describe_instances.side_effect = _client_error(
            "ThrottlingException"
        )

        with patch(
            "lablink_cli.commands.setup._get_session", mock_get_session
        ):
            with pytest.raises(AwsQueryError) as exc:
                query_ec2_instances("us-east-1", "tag")

        assert exc.value.is_auth is False


# ------------------------------------------------------------------
# _classify_aws_error
# ------------------------------------------------------------------
class TestClassifyAwsError:
    def test_no_credentials_is_auth(self):
        err = _classify_aws_error(NoCredentialsError())
        assert err.is_auth is True
        assert "credential" in str(err).lower()

    def test_sso_token_expiry_is_auth(self):
        err = _classify_aws_error(
            TokenRetrievalError(provider="sso", error_msg="token expired")
        )
        assert err.is_auth is True
        assert "sso" in str(err).lower()

    def test_profile_not_found_is_auth(self):
        err = _classify_aws_error(ProfileNotFound(profile="nope"))
        assert err.is_auth is True
        assert "profile" in str(err).lower()

    @pytest.mark.parametrize(
        "code",
        [
            "AuthFailure",
            "ExpiredToken",
            "ExpiredTokenException",
            "RequestExpired",
            "InvalidClientTokenId",
            "SignatureDoesNotMatch",
            "UnrecognizedClientException",
        ],
    )
    def test_authentication_codes(self, code):
        """Identity could not be established — new credentials fix it."""
        err = _classify_aws_error(_client_error(code))
        assert err.is_auth is True, code
        assert err.is_permission is False, code
        assert code in str(err)

    @pytest.mark.parametrize(
        "code",
        ["AccessDenied", "AccessDeniedException", "UnauthorizedOperation"],
    )
    def test_authorization_codes(self, code):
        """Identity is fine but lacks permission — only IAM fixes it, so
        these must not be lumped in with 'go re-authenticate'."""
        err = _classify_aws_error(_client_error(code))
        assert err.is_permission is True, code
        assert err.is_auth is False, code
        assert code in str(err)

    def test_unrelated_client_error_is_neither(self):
        err = _classify_aws_error(_client_error("InvalidParameterValue"))
        assert err.is_auth is False
        assert err.is_permission is False

    def test_arbitrary_exception_is_neither(self):
        err = _classify_aws_error(RuntimeError("boom"))
        assert err.is_auth is False
        assert err.is_permission is False
        assert "boom" in str(err)


# ------------------------------------------------------------------
# print_aws_error — the remedy must match the failure
# ------------------------------------------------------------------
class TestPrintAwsError:
    def test_authentication_gets_credential_steps(self, capsys):
        print_aws_error(AwsQueryError("expired", is_auth=True))
        out = capsys.readouterr().out
        assert "aws configure" in out
        assert "lack permission" not in out

    def test_authorization_gets_iam_guidance_not_credential_steps(
        self, capsys
    ):
        """Telling someone to run 'aws configure' cannot fix a missing IAM
        permission — their credentials are already valid."""
        print_aws_error(
            AwsQueryError(
                "AWS denied the request: UnauthorizedOperation — "
                "not authorized to perform ec2:DescribeInstances",
                is_permission=True,
            )
        )
        out = capsys.readouterr().out
        assert "aws configure" not in out
        assert "aws sso login" not in out
        assert "lack permission" in out
        assert "ec2:DescribeInstances" in out

    def test_other_errors_get_no_remedy(self, capsys):
        print_aws_error(AwsQueryError("ThrottlingException: slow down"))
        out = capsys.readouterr().out
        assert "ThrottlingException" in out
        assert "aws configure" not in out
        assert "lack permission" not in out

    def test_prefix_is_used_when_given(self, capsys):
        print_aws_error(AwsQueryError("boom"), prefix="Could not query EC2")
        assert "Could not query EC2: boom" in capsys.readouterr().out


# ------------------------------------------------------------------
# aws_credentials_error
# ------------------------------------------------------------------
class TestAwsCredentialsError:
    @patch("lablink_cli.commands.utils._get_session", create=True)
    def test_returns_none_when_valid(self, mock_get_session):
        mock_sts = MagicMock()
        mock_get_session.return_value.client.return_value = mock_sts
        mock_sts.get_caller_identity.return_value = {
            "Account": "123456789012",
            "Arn": "arn:aws:iam::123456789012:user/me",
            "UserId": "AIDA",
        }

        with patch(
            "lablink_cli.commands.setup._get_session", mock_get_session
        ):
            assert aws_credentials_error("us-east-1") is None

    @patch("lablink_cli.commands.utils._get_session", create=True)
    def test_returns_auth_error_when_missing(self, mock_get_session):
        mock_sts = MagicMock()
        mock_get_session.return_value.client.return_value = mock_sts
        mock_sts.get_caller_identity.side_effect = NoCredentialsError()

        with patch(
            "lablink_cli.commands.setup._get_session", mock_get_session
        ):
            err = aws_credentials_error("us-east-1")

        assert isinstance(err, AwsQueryError)
        assert err.is_auth is True

    @patch("lablink_cli.commands.utils._get_session", create=True)
    def test_returns_auth_error_when_expired(self, mock_get_session):
        mock_sts = MagicMock()
        mock_get_session.return_value.client.return_value = mock_sts
        mock_sts.get_caller_identity.side_effect = _client_error(
            "ExpiredToken"
        )

        with patch(
            "lablink_cli.commands.setup._get_session", mock_get_session
        ):
            err = aws_credentials_error("us-east-1")

        assert err is not None
        assert err.is_auth is True

    @patch("lablink_cli.commands.utils._get_session", create=True)
    def test_does_not_print(self, mock_get_session, capsys):
        """Unlike setup.check_credentials, the probe must stay quiet.

        status/logs render their own message; a red wall printed from
        inside the probe would duplicate it (and corrupt doctor-style
        tables).
        """
        mock_sts = MagicMock()
        mock_get_session.return_value.client.return_value = mock_sts
        mock_sts.get_caller_identity.side_effect = NoCredentialsError()

        with patch(
            "lablink_cli.commands.setup._get_session", mock_get_session
        ):
            aws_credentials_error("us-east-1")

        assert capsys.readouterr().out == ""


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
# get_tofu_outputs
# ------------------------------------------------------------------
class TestGetTofuOutputs:
    def test_valid_output(self, tmp_path):
        tf_output = json.dumps({
            "ec2_public_ip": {"value": "10.0.0.1"},
            "private_key_pem": {"value": "-----BEGIN RSA PRIVATE KEY-----"},
        })
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout=tf_output, returncode=0)
            result = get_tofu_outputs(tmp_path)

        assert result == {
            "ec2_public_ip": "10.0.0.1",
            "private_key_pem": "-----BEGIN RSA PRIVATE KEY-----",
        }
        mock_run.assert_called_once_with(
            ["tofu", "output", "-json"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        )

    def test_subprocess_error_raises_with_reason(self, tmp_path):
        """A failed read must not masquerade as an absent deployment."""
        stderr = (
            "\x1b[31m\u2577\x1b[0m\n"
            "\u2502 Error: validating provider credentials: "
            "api error InvalidClientTokenId\n"
            "\u2575\n"
        )
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "tofu", stderr=stderr
            )
            with pytest.raises(TofuError) as excinfo:
                get_tofu_outputs(tmp_path)

        msg = str(excinfo.value)
        assert "InvalidClientTokenId" in msg
        # ANSI and tofu's box drawing must not survive into the message.
        assert "\x1b" not in msg
        assert "\u2502" not in msg

    def test_missing_binary_raises(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError()
            with pytest.raises(TofuError, match="not found on PATH"):
                get_tofu_outputs(tmp_path)

    def test_invalid_json_raises(self, tmp_path):
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="not json", returncode=0)
            with pytest.raises(TofuError, match="could not parse"):
                get_tofu_outputs(tmp_path)

    def test_empty_output_is_not_an_error(self, tmp_path):
        """`tofu output -json` exits 0 with `{}` when the state declares no
        outputs — including in an uninitialised directory. That is a real
        empty result, not a failure."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="{}", returncode=0)
            result = get_tofu_outputs(tmp_path)

        assert result == {}
