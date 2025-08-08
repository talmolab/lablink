import pytest
from unittest.mock import patch, MagicMock
from botocore.exceptions import ClientError
import utils.aws_utils as aws_utils  # <-- your actual module path


@patch("utils.aws_utils.boto3.client")
def test_validate_aws_credentials_success(mock_boto_client):
    mock_sts = MagicMock()
    mock_sts.get_caller_identity.return_value = {
        "UserId": "ABC123",
        "Account": "456789",
        "Arn": "arn:aws:iam::456789:user/Test",
    }
    mock_boto_client.return_value = mock_sts

    result = aws_utils.validate_aws_credentials()
    assert result == {"valid": True}
    mock_sts.get_caller_identity.assert_called_once()


@patch("utils.aws_utils.boto3.client")
def test_validate_aws_credentials_failure_invalid_token(mock_boto_client):
    mock_sts = MagicMock()
    mock_sts.get_caller_identity.side_effect = ClientError(
        error_response={
            "Error": {"Code": "InvalidClientTokenId", "Message": "Invalid token"}
        },
        operation_name="GetCallerIdentity",
    )
    mock_boto_client.return_value = mock_sts

    result = aws_utils.validate_aws_credentials()
    assert result["valid"] is False
    assert "temporary but no session token" in result["message"]


@patch("utils.aws_utils.boto3.client")
def test_validate_aws_credentials_failure_invalid_keys_and_ids(mock_boto_client):
    mock_sts = MagicMock()
    mock_sts.get_caller_identity.side_effect = ClientError(
        error_response={
            "Error": {
                "Code": "AuthorizationHeaderMalformed",
                "Message": "The authorization header that you provided is not valid.",
            }
        },
        operation_name="GetCallerIdentity",
    )
    mock_boto_client.return_value = mock_sts

    result = aws_utils.validate_aws_credentials()

    assert result["valid"] is False
    assert "authorization header" in result["message"].lower()


@patch("utils.aws_utils.boto3.client")
def test_get_all_instance_types(mock_boto_client):
    paginator = MagicMock()
    paginator.paginate.return_value = [
        {
            "InstanceTypes": [
                {"InstanceType": "t2.micro"},
                {"InstanceType": "g4dn.xlarge"},
            ]
        }
    ]

    mock_ec2 = MagicMock()
    mock_ec2.get_paginator.return_value = paginator
    mock_boto_client.return_value = mock_ec2

    result = aws_utils.get_all_instance_types()
    assert "t2.micro" in result
    assert "g4dn.xlarge" in result


@patch("utils.aws_utils.boto3.client")
def test_check_support_nvidia_true(mock_boto_client):
    mock_ec2 = MagicMock()
    mock_ec2.describe_instance_types.return_value = {
        "InstanceTypes": [
            {"GpuInfo": {"Gpus": [{"Manufacturer": "NVIDIA", "Count": 1}]}}
        ]
    }
    mock_boto_client.return_value = mock_ec2

    assert aws_utils.check_support_nvidia("g4dn.xlarge") is True


@patch("utils.aws_utils.boto3.client")
def test_check_support_nvidia_false(mock_boto_client):
    mock_ec2 = MagicMock()
    mock_ec2.describe_instance_types.return_value = {
        "InstanceTypes": [{"GpuInfo": {"Gpus": [{"Manufacturer": "AMD"}]}}]
    }
    mock_boto_client.return_value = mock_ec2

    assert aws_utils.check_support_nvidia("t2.micro") is False


@patch("utils.aws_utils.boto3.client")
def test_check_support_nvidia_no_gpuinfo(mock_boto_client):
    mock_ec2 = MagicMock()
    mock_ec2.describe_instance_types.return_value = {
        "InstanceTypes": [{}]  # No GpuInfo at all
    }
    mock_boto_client.return_value = mock_ec2

    assert aws_utils.check_support_nvidia("t2.micro") is False
