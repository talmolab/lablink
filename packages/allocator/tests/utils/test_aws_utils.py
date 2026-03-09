from types import SimpleNamespace
from unittest.mock import patch, MagicMock
import lablink_allocator_service.utils.aws_utils as aws_utils


@patch("lablink_allocator_service.utils.aws_utils.boto3.client")
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


@patch("lablink_allocator_service.utils.aws_utils.boto3.client")
def test_check_support_nvidia_true(mock_boto_client):
    mock_ec2 = MagicMock()
    mock_ec2.describe_instance_types.return_value = {
        "InstanceTypes": [
            {"GpuInfo": {"Gpus": [{"Manufacturer": "NVIDIA", "Count": 1}]}}
        ]
    }
    mock_boto_client.return_value = mock_ec2

    assert aws_utils.check_support_nvidia("g4dn.xlarge") is True


@patch("lablink_allocator_service.utils.aws_utils.boto3.client")
def test_check_support_nvidia_false(mock_boto_client):
    mock_ec2 = MagicMock()
    mock_ec2.describe_instance_types.return_value = {
        "InstanceTypes": [{"GpuInfo": {"Gpus": [{"Manufacturer": "AMD"}]}}]
    }
    mock_boto_client.return_value = mock_ec2

    assert aws_utils.check_support_nvidia("t2.micro") is False


@patch("lablink_allocator_service.utils.aws_utils.boto3.client")
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


@patch("lablink_allocator_service.utils.aws_utils.boto3.client")
def test_get_instance_id_by_name_found(mock_boto_client):
    """Test finding an EC2 instance by Name tag."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {"InstanceId": "i-abc123"}
                ]
            }
        ]
    }
    mock_boto_client.return_value = mock_ec2

    result = aws_utils.get_instance_id_by_name("test-vm-1", region="us-west-2")

    assert result == "i-abc123"
    mock_ec2.describe_instances.assert_called_once()
    filters = mock_ec2.describe_instances.call_args[1]["Filters"]
    assert {"Name": "tag:Name", "Values": ["test-vm-1"]} in filters


@patch("lablink_allocator_service.utils.aws_utils.boto3.client")
def test_get_instance_id_by_name_not_found(mock_boto_client):
    """Test when no instance matches the Name tag."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {"Reservations": []}
    mock_boto_client.return_value = mock_ec2

    result = aws_utils.get_instance_id_by_name("nonexistent-vm")

    assert result is None


@patch("lablink_allocator_service.utils.aws_utils.boto3.client")
def test_get_instance_id_by_name_client_error(mock_boto_client):
    """Test error handling in get_instance_id_by_name."""
    from botocore.exceptions import ClientError

    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.side_effect = ClientError(
        {"Error": {"Code": "UnauthorizedAccess", "Message": "Access denied"}},
        "DescribeInstances",
    )
    mock_boto_client.return_value = mock_ec2

    result = aws_utils.get_instance_id_by_name("test-vm-1")

    assert result is None


@patch("lablink_allocator_service.utils.aws_utils.boto3.client")
def test_get_instance_public_ip_found(mock_boto_client):
    """Test getting public IP of an EC2 instance."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {"InstanceId": "i-abc123", "PublicIpAddress": "1.2.3.4"}
                ]
            }
        ]
    }
    mock_boto_client.return_value = mock_ec2

    result = aws_utils.get_instance_public_ip("i-abc123", region="us-west-2")

    assert result == "1.2.3.4"
    mock_ec2.describe_instances.assert_called_once_with(InstanceIds=["i-abc123"])


@patch("lablink_allocator_service.utils.aws_utils.boto3.client")
def test_get_instance_public_ip_not_found(mock_boto_client):
    """Test getting public IP when instance has none."""
    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.return_value = {
        "Reservations": [
            {
                "Instances": [
                    {"InstanceId": "i-abc123"}  # No PublicIpAddress
                ]
            }
        ]
    }
    mock_boto_client.return_value = mock_ec2

    result = aws_utils.get_instance_public_ip("i-abc123")

    assert result is None


@patch("lablink_allocator_service.utils.aws_utils.boto3.client")
def test_get_instance_public_ip_client_error(mock_boto_client):
    """Test error handling in get_instance_public_ip."""
    from botocore.exceptions import ClientError

    mock_ec2 = MagicMock()
    mock_ec2.describe_instances.side_effect = ClientError(
        {"Error": {"Code": "InvalidInstanceID", "Message": "Not found"}},
        "DescribeInstances",
    )
    mock_boto_client.return_value = mock_ec2

    result = aws_utils.get_instance_public_ip("i-invalid")

    assert result is None


@patch("lablink_allocator_service.utils.aws_utils.boto3.client")
def test_stop_start_ec2_instance_success(mock_boto_client):
    """Test successful stop/start of an EC2 instance."""
    mock_ec2 = MagicMock()
    mock_waiter = MagicMock()
    mock_ec2.get_waiter.return_value = mock_waiter
    mock_boto_client.return_value = mock_ec2

    result = aws_utils.stop_start_ec2_instance("i-abc123", region="us-west-2")

    assert result is True
    mock_ec2.stop_instances.assert_called_once_with(InstanceIds=["i-abc123"])
    mock_waiter.wait.assert_called_once_with(
        InstanceIds=["i-abc123"],
        WaiterConfig={"Delay": 10, "MaxAttempts": 40},
    )
    mock_ec2.start_instances.assert_called_once_with(InstanceIds=["i-abc123"])


@patch("lablink_allocator_service.utils.aws_utils.boto3.client")
def test_stop_start_ec2_instance_failure(mock_boto_client):
    """Test stop/start failure."""
    from botocore.exceptions import ClientError

    mock_ec2 = MagicMock()
    mock_ec2.stop_instances.side_effect = ClientError(
        {"Error": {"Code": "InvalidInstanceID", "Message": "Not found"}},
        "StopInstances",
    )
    mock_boto_client.return_value = mock_ec2

    result = aws_utils.stop_start_ec2_instance("i-invalid")

    assert result is False


