"""Clean up orphaned AWS resources and local state."""

from __future__ import annotations

import shutil

import boto3
from botocore.exceptions import ClientError
from rich.console import Console
from rich.panel import Panel

from lablink_allocator_service.conf.structured_config import Config

from lablink_cli.commands.setup import (
    _get_session,
    check_credentials,
    resolve_bucket_name,
)
from lablink_cli.commands.utils import (
    get_deploy_dir as _get_deploy_dir,
)

console = Console()


def _delete_if_exists(
    action: str, fn, *args, **kwargs
) -> bool:
    """Call fn and return True on success, False if not found."""
    try:
        fn(*args, **kwargs)
        console.print(f"  [green]deleted[/green] {action}")
        return True
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in (
            "NotFoundException",
            "ResourceNotFoundException",
            "NoSuchEntity",
            "InvalidParameterValue",
            "InvalidKeyPair.NotFound",
            "InvalidGroup.NotFound",
            "404",
        ):
            console.print(
                f"  [dim]not found[/dim] {action}"
            )
            return False
        raise


# ------------------------------------------------------------------
# EC2 resources
# ------------------------------------------------------------------
def cleanup_ec2_instances(
    ec2, region: str, deployment_name: str, environment: str, dry_run: bool
) -> None:
    """Terminate lablink EC2 instances."""
    console.print("[bold]EC2 Instances[/bold]")
    resp = ec2.describe_instances(
        Filters=[
            {
                "Name": "tag:Name",
                "Values": [
                    f"{deployment_name}-allocator-{environment}",
                    f"*-lablink-client-{environment}-vm-*",
                ],
            },
            {
                "Name": "instance-state-name",
                "Values": [
                    "running",
                    "stopped",
                    "pending",
                ],
            },
        ]
    )
    instance_ids = [
        i["InstanceId"]
        for r in resp["Reservations"]
        for i in r["Instances"]
    ]
    if not instance_ids:
        console.print("  [dim]none found[/dim]")
        return

    for iid in instance_ids:
        if dry_run:
            console.print(
                f"  [yellow]would terminate[/yellow] {iid}"
            )
        else:
            ec2.terminate_instances(InstanceIds=[iid])
            console.print(
                f"  [green]terminated[/green] {iid}"
            )

    if not dry_run and instance_ids:
        console.print("  waiting for termination...")
        waiter = ec2.get_waiter("instance_terminated")
        waiter.wait(InstanceIds=instance_ids)
        console.print("  [green]done[/green]")


def cleanup_security_groups(
    ec2, deployment_name: str, environment: str, dry_run: bool
) -> None:
    """Delete lablink security groups."""
    console.print("[bold]Security Groups[/bold]")
    found = False
    for pattern in [
        f"{deployment_name}-allocator-sg-{environment}",
        f"*-lablink-client-{environment}-sg",
        f"{deployment_name}-alb-sg-{environment}",
    ]:
        resp = ec2.describe_security_groups(
            Filters=[
                {"Name": "group-name", "Values": [pattern]}
            ]
        )
        for sg in resp["SecurityGroups"]:
            found = True
            if dry_run:
                console.print(
                    f"  [yellow]would delete[/yellow] "
                    f"{sg['GroupName']} ({sg['GroupId']})"
                )
            else:
                _delete_if_exists(
                    f"{sg['GroupName']} ({sg['GroupId']})",
                    ec2.delete_security_group,
                    GroupId=sg["GroupId"],
                )
    if not found:
        console.print("  [dim]none found[/dim]")


def cleanup_key_pairs(
    ec2, deployment_name: str, environment: str, software: str, dry_run: bool
) -> None:
    """Delete lablink key pairs."""
    console.print("[bold]Key Pairs[/bold]")
    found = False
    for name in [
        f"{deployment_name}-keypair-{environment}",
        f"{software}-lablink-client-{environment}-keypair",
    ]:
        try:
            ec2.describe_key_pairs(KeyNames=[name])
            found = True
            if dry_run:
                console.print(
                    f"  [yellow]would delete[/yellow] {name}"
                )
            else:
                _delete_if_exists(
                    name,
                    ec2.delete_key_pair,
                    KeyName=name,
                )
        except ClientError:
            pass
    if not found:
        console.print("  [dim]none found[/dim]")


def cleanup_elastic_ips(
    ec2, deployment_name: str, environment: str, dry_run: bool
) -> None:
    """Release lablink elastic IPs."""
    console.print("[bold]Elastic IPs[/bold]")
    resp = ec2.describe_addresses(
        Filters=[
            {
                "Name": "tag:Name",
                "Values": [f"{deployment_name}-eip-{environment}"],
            }
        ]
    )
    if not resp["Addresses"]:
        console.print("  [dim]none found[/dim]")
        return

    for addr in resp["Addresses"]:
        alloc_id = addr["AllocationId"]
        ip = addr.get("PublicIp", "")
        if dry_run:
            console.print(
                f"  [yellow]would release[/yellow] "
                f"{ip} ({alloc_id})"
            )
        else:
            # Disassociate first if attached
            if "AssociationId" in addr:
                ec2.disassociate_address(
                    AssociationId=addr["AssociationId"]
                )
            ec2.release_address(AllocationId=alloc_id)
            console.print(
                f"  [green]released[/green] "
                f"{ip} ({alloc_id})"
            )


# ------------------------------------------------------------------
# IAM resources
# ------------------------------------------------------------------
def _cleanup_instance_profile(
    iam, profile_name: str, dry_run: bool
) -> None:
    """Delete an IAM instance profile, detaching roles first."""
    try:
        resp = iam.get_instance_profile(
            InstanceProfileName=profile_name
        )
        if dry_run:
            console.print(
                f"  [yellow]would delete[/yellow] "
                f"profile: {profile_name}"
            )
        else:
            for role in resp["InstanceProfile"].get(
                "Roles", []
            ):
                iam.remove_role_from_instance_profile(
                    InstanceProfileName=profile_name,
                    RoleName=role["RoleName"],
                )
            iam.delete_instance_profile(
                InstanceProfileName=profile_name
            )
            console.print(
                f"  [green]deleted[/green] "
                f"profile: {profile_name}"
            )
    except ClientError:
        pass


def _cleanup_role(
    iam, role_name: str, dry_run: bool
) -> None:
    """Delete an IAM role, detaching policies first."""
    try:
        resp = iam.list_attached_role_policies(
            RoleName=role_name
        )
        for policy in resp["AttachedPolicies"]:
            if not dry_run:
                iam.detach_role_policy(
                    RoleName=role_name,
                    PolicyArn=policy["PolicyArn"],
                )
        if dry_run:
            console.print(
                f"  [yellow]would delete[/yellow] "
                f"role: {role_name}"
            )
        else:
            iam.delete_role(RoleName=role_name)
            console.print(
                f"  [green]deleted[/green] "
                f"role: {role_name}"
            )
    except ClientError:
        pass


def cleanup_iam(
    session: boto3.Session,
    deployment_name: str,
    environment: str,
    software: str,
    dry_run: bool,
) -> None:
    """Delete lablink IAM roles, policies, instance profiles."""
    console.print("[bold]IAM Resources[/bold]")
    iam = session.client("iam")
    account_id = (
        session.client("sts").get_caller_identity()["Account"]
    )

    client_prefix = f"{software}-lablink-client-{environment}"

    # Instance profiles (allocator + client)
    for profile_name in [
        f"{deployment_name}-allocator-profile-{environment}",
        f"{client_prefix}-instance-profile",
    ]:
        _cleanup_instance_profile(iam, profile_name, dry_run)

    # Roles (allocator + client)
    for role_name in [
        f"{deployment_name}-allocator-role-{environment}",
        f"{client_prefix}-vm-role",
    ]:
        _cleanup_role(iam, role_name, dry_run)

    # Policies
    for policy_name in [
        f"{deployment_name}-s3-backend-policy-{environment}",
        f"{deployment_name}-ec2-mgmt-policy-{environment}",
    ]:
        arn = (
            f"arn:aws:iam::{account_id}:policy/{policy_name}"
        )
        if dry_run:
            try:
                iam.get_policy(PolicyArn=arn)
                console.print(
                    f"  [yellow]would delete[/yellow] "
                    f"policy: {policy_name}"
                )
            except ClientError:
                pass
        else:
            _delete_if_exists(
                f"policy: {policy_name}",
                iam.delete_policy,
                PolicyArn=arn,
            )


# ------------------------------------------------------------------
# S3 environment state cleanup
# ------------------------------------------------------------------
def cleanup_s3_env_state(
    session: boto3.Session,
    deployment_name: str,
    environment: str,
    dry_run: bool,
) -> None:
    """Delete environment-specific Terraform state files from S3."""
    console.print("[bold]S3 Terraform State[/bold]")
    account_id = (
        session.client("sts").get_caller_identity()["Account"]
    )
    bucket_name = resolve_bucket_name(account_id)
    s3 = session.client("s3")

    try:
        s3.head_bucket(Bucket=bucket_name)
    except ClientError:
        console.print(
            f"  [dim]bucket not found:[/dim] {bucket_name}"
        )
        return

    prefix = f"{deployment_name}/{environment}/"
    try:
        resp = s3.list_object_versions(
            Bucket=bucket_name, Prefix=prefix
        )
        versions = resp.get("Versions", []) + resp.get(
            "DeleteMarkers", []
        )
        if not versions:
            console.print("  [dim]no state files found[/dim]")
            return

        for v in versions:
            key = v["Key"]
            vid = v["VersionId"]
            if dry_run:
                console.print(
                    f"  [yellow]would delete[/yellow] "
                    f"s3://{bucket_name}/{key} ({vid})"
                )
            else:
                s3.delete_object(
                    Bucket=bucket_name,
                    Key=key,
                    VersionId=vid,
                )
                console.print(
                    f"  [green]deleted[/green] "
                    f"s3://{bucket_name}/{key}"
                )
    except ClientError as e:
        console.print(f"  [red]error:[/red] {e}")


# ------------------------------------------------------------------
# DynamoDB environment lock entries
# ------------------------------------------------------------------
def cleanup_dynamodb_env_locks(
    session: boto3.Session,
    deployment_name: str,
    environment: str,
    bucket_name: str,
    dry_run: bool,
) -> None:
    """Delete environment-specific lock entries from DynamoDB."""
    console.print("[bold]DynamoDB Lock Entries[/bold]")
    dynamodb = session.client("dynamodb")
    table_name = "lock-table"

    lock_ids = [
        f"{bucket_name}/{deployment_name}/{environment}"
        f"/terraform.tfstate-md5",
        f"{bucket_name}/{deployment_name}/{environment}"
        f"/client/terraform.tfstate-md5",
    ]

    found = False
    for lock_id in lock_ids:
        try:
            resp = dynamodb.get_item(
                TableName=table_name,
                Key={"LockID": {"S": lock_id}},
            )
            if "Item" not in resp:
                continue
            found = True
            if dry_run:
                console.print(
                    f"  [yellow]would delete[/yellow] {lock_id}"
                )
            else:
                dynamodb.delete_item(
                    TableName=table_name,
                    Key={"LockID": {"S": lock_id}},
                )
                console.print(
                    f"  [green]deleted[/green] {lock_id}"
                )
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code == "ResourceNotFoundException":
                console.print(
                    "  [dim]lock table not found[/dim]"
                )
                return
            raise
    if not found:
        console.print("  [dim]no lock entries found[/dim]")


# ------------------------------------------------------------------
# Local state
# ------------------------------------------------------------------
def cleanup_local(cfg: Config, dry_run: bool) -> None:
    """Delete local Terraform working directory."""
    console.print("[bold]Local State[/bold]")
    deploy_dir = _get_deploy_dir(cfg)
    if deploy_dir.exists():
        if dry_run:
            console.print(
                f"  [yellow]would delete[/yellow] {deploy_dir}"
            )
        else:
            shutil.rmtree(deploy_dir)
            console.print(
                f"  [green]deleted[/green] {deploy_dir}"
            )
    else:
        console.print("  [dim]not found[/dim]")


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------
def run_cleanup(
    cfg: Config,
    dry_run: bool = False,
) -> None:
    """Clean up orphaned AWS resources."""
    region = cfg.app.region
    deployment_name = cfg.deployment_name
    environment = cfg.environment
    software = cfg.machine.software

    console.print()
    mode = "[yellow]DRY RUN[/yellow] " if dry_run else ""
    console.print(
        Panel(
            f"{mode}[bold]LabLink Cleanup[/bold]\n"
            f"Deployment: {deployment_name}  |  "
            f"Environment: {environment}\n"
            f"Region: {region}",
            border_style="red" if not dry_run else "yellow",
        )
    )
    console.print()

    session = _get_session(region)
    check_credentials(session)
    ec2 = session.client("ec2")

    # AWS resources matching current Terraform
    cleanup_ec2_instances(ec2, region, deployment_name, environment, dry_run)
    console.print()
    cleanup_security_groups(ec2, deployment_name, environment, dry_run)
    console.print()
    cleanup_key_pairs(ec2, deployment_name, environment, software, dry_run)
    console.print()
    cleanup_elastic_ips(ec2, deployment_name, environment, dry_run)
    console.print()
    cleanup_iam(session, deployment_name, environment, software, dry_run)
    console.print()

    # Environment-specific remote state
    account_id = (
        session.client("sts").get_caller_identity()["Account"]
    )
    bucket_name = resolve_bucket_name(account_id)
    cleanup_s3_env_state(
        session, deployment_name, environment, dry_run
    )
    console.print()
    cleanup_dynamodb_env_locks(
        session, deployment_name, environment, bucket_name, dry_run
    )
    console.print()

    # Local state
    cleanup_local(cfg, dry_run)
    console.print()

    if dry_run:
        console.print(
            "[yellow]Dry run complete.[/yellow] "
            "Re-run without --dry-run to delete."
        )
    else:
        console.print("[bold]Cleanup complete.[/bold]")
