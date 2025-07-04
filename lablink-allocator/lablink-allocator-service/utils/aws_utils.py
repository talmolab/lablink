import os
import logging

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_all_instance_types(region="us-west-2"):
    """Fetch all available EC2 instance types in a given AWS region.
    Args:
        region (str): The AWS region to query for instance types. Default is 'us-west-2'.
    Returns:
        list: A list of available EC2 instance types in the specified region.
    """
    ec2 = boto3.client(
        "ec2",
        region_name=region,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
    )
    instance_types = []
    paginator = ec2.get_paginator("describe_instance_types")
    for page in paginator.paginate():
        for itype in page["InstanceTypes"]:
            instance_types.append(itype["InstanceType"])
    return instance_types


def validate_aws_credentials() -> bool:
    """Validate AWS credentials by attempting to list EC2 instance types.
    Returns:
        bool: True if credentials are valid, False otherwise.
    """
    try:
        # Attempt to create a client and call a simple API to validate credentials
        client = boto3.client(
            "sts",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
        )
        client.get_caller_identity()
        logger.info("AWS credentials are valid.")
        return True
    except ClientError as e:
        logger.error(f"Error validating AWS credentials: {e}")
        return False
