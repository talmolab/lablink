import os
import logging
from pathlib import Path
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_all_instance_types(region="us-west-2"):
    """Fetch all available EC2 instance types in a given AWS region.
    Args:
        region (str): The AWS region to query for instance types.
    Returns:
        list: A list of available EC2 instance types in the specified region.
    """
    kwargs = {
        "region_name": region,
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
    }
    if os.getenv("AWS_SESSION_TOKEN"):
        kwargs["aws_session_token"] = os.getenv("AWS_SESSION_TOKEN")

    ec2 = boto3.client("ec2", **kwargs)
    instance_types = []
    paginator = ec2.get_paginator("describe_instance_types")
    for page in paginator.paginate():
        for itype in page["InstanceTypes"]:
            instance_types.append(itype["InstanceType"])
    return instance_types


def check_support_nvidia(machine_type) -> bool:
    """Check if a given EC2 instance type supports NVIDIA GPUs.
    Args:
        machine_type (str): The EC2 instance type to check.
    Returns:
        bool: True if the instance type supports NVIDIA GPUs, False otherwise.
    """
    kwargs = {
        "region_name": os.getenv("AWS_REGION", "us-west-2"),
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
    }
    if os.getenv("AWS_SESSION_TOKEN"):
        kwargs["aws_session_token"] = os.getenv("AWS_SESSION_TOKEN")

    ec2 = boto3.client("ec2", **kwargs)
    try:
        response = ec2.describe_instance_types(InstanceTypes=[machine_type])
        gpu_info = response["InstanceTypes"][0].get("GpuInfo", {})

        # Check if GPU is present
        if not gpu_info:
            logger.debug(f"No GPU info found for instance type {machine_type}.")
            return False

        # Check if any GPU supports NVIDIA
        for gpu in gpu_info.get("Gpus", []):
            if "NVIDIA" in gpu.get("Manufacturer", ""):
                logger.info(f"Instance type {machine_type} supports NVIDIA GPUs.")
                return True

        logger.debug(f"Instance type {machine_type} does not support NVIDIA GPUs.")
    except ClientError as e:
        logger.error(f"Error checking NVIDIA support for {machine_type}: {e}")
    return False


def get_instance_id_by_name(name: str, region: str = "us-west-2") -> Optional[str]:
    """Look up an EC2 instance ID by its Name tag.

    Args:
        name: The Name tag value of the EC2 instance.
        region: The AWS region to search in.

    Returns:
        The instance ID if found, None otherwise.
    """
    kwargs = {
        "region_name": region,
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
    }
    if os.getenv("AWS_SESSION_TOKEN"):
        kwargs["aws_session_token"] = os.getenv("AWS_SESSION_TOKEN")

    ec2 = boto3.client("ec2", **kwargs)
    try:
        response = ec2.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [name]},
                {
                    "Name": "instance-state-name",
                    "Values": ["running", "stopped", "pending"],
                },
            ]
        )
        for reservation in response.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                return instance["InstanceId"]
    except ClientError as e:
        logger.error(f"Error looking up instance by name '{name}': {e}")
    return None


def get_instance_public_ip(
    instance_id: str, region: str = "us-west-2"
) -> Optional[str]:
    """Get the public IP address of an EC2 instance.

    Args:
        instance_id: The EC2 instance ID.
        region: The AWS region where the instance is located.

    Returns:
        The public IP address if available, None otherwise.
    """
    kwargs = {
        "region_name": region,
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
    }
    if os.getenv("AWS_SESSION_TOKEN"):
        kwargs["aws_session_token"] = os.getenv("AWS_SESSION_TOKEN")

    ec2 = boto3.client("ec2", **kwargs)
    try:
        response = ec2.describe_instances(InstanceIds=[instance_id])
        for reservation in response.get("Reservations", []):
            for instance in reservation.get("Instances", []):
                ip = instance.get("PublicIpAddress")
                if ip:
                    return ip
    except ClientError as e:
        logger.error(f"Error getting public IP for instance {instance_id}: {e}")
    return None


def stop_start_ec2_instance(instance_id: str, region: str = "us-west-2") -> bool:
    """Stop and start an EC2 instance (last-resort fallback).

    Calls stop_instances, waits for stopped state, then starts again.
    Note: This does NOT clear cloud-init state, so user_data.sh will
    not re-run. This is a best-effort restart for cases where SSH is
    unreachable (e.g., hung processes, OOM).

    Args:
        instance_id: The EC2 instance ID.
        region: The AWS region where the instance is located.

    Returns:
        True if stop/start completed successfully, False otherwise.
    """
    kwargs = {
        "region_name": region,
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
    }
    if os.getenv("AWS_SESSION_TOKEN"):
        kwargs["aws_session_token"] = os.getenv("AWS_SESSION_TOKEN")

    ec2 = boto3.client("ec2", **kwargs)
    try:
        logger.info(f"Stopping instance {instance_id}...")
        ec2.stop_instances(InstanceIds=[instance_id])
        waiter = ec2.get_waiter("instance_stopped")
        waiter.wait(
            InstanceIds=[instance_id],
            WaiterConfig={"Delay": 10, "MaxAttempts": 40},
        )
        logger.info(f"Instance {instance_id} stopped, starting...")
        ec2.start_instances(InstanceIds=[instance_id])
        logger.info(f"Start initiated for instance {instance_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to stop/start instance {instance_id}: {e}")
        return False


def upload_to_s3(
    local_path: Path,
    env: str,
    bucket_name: str,
    region: str,
    deployment_name: str = "lablink",
    kms_key_id: Optional[str] = None,
) -> None:
    """Uploads a file to an S3 bucket.

    Args:
        local_path (Path): The local file path to upload.
        env (str): The environment (e.g., dev, test, prod) for the upload.
        bucket_name (str): The name of the S3 bucket to upload to.
        region (str): The AWS region where the S3 bucket is located.
        deployment_name (str): The deployment name for S3 key scoping.
            Defaults to "lablink".
        kms_key_id (Optional[str], optional): The KMS key ID for server-side encryption.
            Defaults to None.
    """
    s3 = boto3.client("s3", region_name=region)
    key = f"{deployment_name}/{env}/client/{local_path.name}"
    extra = {"ContentType": "text/plain"}
    if kms_key_id:
        extra.update({"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": kms_key_id})

    # Upload the variable file
    s3.upload_file(local_path, bucket_name, key, ExtraArgs=extra)
