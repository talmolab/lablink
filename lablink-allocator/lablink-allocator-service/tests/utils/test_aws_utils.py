from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from botocore.exceptions import ClientError
import utils.aws_utils as aws_utils


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


def test_upload_to_s3_success(monkeypatch, tmp_path):
    # Prepare a real file so Path handling is realistic
    local_file = tmp_path / "vars.auto.tfvars"
    local_file.write_text('foo="bar"\n')

    # Mock the S3 client and its upload_file method
    mock_s3 = SimpleNamespace(upload_file=MagicMock(name="upload_file"))
    client_mock = MagicMock(return_value=mock_s3)
    monkeypatch.setattr(
        aws_utils, "boto3", SimpleNamespace(client=client_mock), raising=True
    )

    bucket = "tf-state-lablink-allocator-bucket"

    aws_utils.upload_to_s3(
        bucket_name=bucket,
        region="us-west-2",
        local_path=local_file,
        env="test",
    )

    # Assert: region passed to boto3.client
    client_mock.assert_called_once_with("s3", region_name="us-west-2")

    # Assert: upload_file args and ExtraArgs
    expected_key = f"test/client/{local_file.name}"
    mock_s3.upload_file.assert_called_once()
    args, kwargs = mock_s3.upload_file.call_args
    assert args == (local_file, bucket, expected_key)
    assert kwargs["ExtraArgs"] == {"ContentType": "text/plain"}
