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


def validate_aws_credentials() -> dict:
    """Validate AWS credentials by attempting to list EC2 instance types.
    Returns:
        dict: A dictionary indicating whether the credentials are valid.
              If invalid, it includes an error message.
    Raises:
        ClientError: If there is an issue with the AWS credentials.
    """
    try:
        # Prepare the kwargs for boto3 client
        kwargs = {
            "region_name": os.getenv("AWS_REGION", "us-west-2"),
            "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
            "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        }
        if os.getenv("AWS_SESSION_TOKEN"):
            kwargs["aws_session_token"] = os.getenv("AWS_SESSION_TOKEN")

        # Attempt to create a client and call a simple API to validate credentials
        client = boto3.client("sts", **kwargs)
        client.get_caller_identity()
        logger.info("AWS credentials are valid.")
        return {"valid": True}
    except ClientError as e:
        if "InvalidClientTokenId" in str(e):
            message = "AWS credentials are temporary but no session token provided."
            logger.error(message)
            return {
                "valid": False,
                "message": message,
            }
        else:
            logger.error(f"Error validating AWS credentials: {e}")
            return {"valid": False, "message": str(e)}


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


def upload_to_s3(
        local_path: Path,
        env: str,
        bucket_name: str,
        region: str,
        kms_key_id: Optional[str] = None,
    ) -> None:
    """Uploads a file to an S3 bucket.

    Args:
        local_path (Path): The local file path to upload.
        env (str): The environment (e.g., dev, test, prod) for the upload.
        bucket_name (str): The name of the S3 bucket to upload to.
        region (str): The AWS region where the S3 bucket is located.
        kms_key_id (Optional[str], optional): The KMS key ID for server-side encryption.
            Defaults to None.
    """
    s3 = boto3.client("s3", region_name=region)
    key = f"{env}/client/{local_path.name}"
    extra = {"ContentType": "text/plain"}
    if kms_key_id:
        extra.update({"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": kms_key_id})

    # Upload the variable file
    s3.upload_file(local_path, bucket_name, key, ExtraArgs=extra)
