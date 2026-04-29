"""AWS bootstrapping for LabLink (S3, DynamoDB, Route53).

Replaces the template repo's setup.sh with boto3 calls.
Creates the infrastructure needed before `lablink deploy` can run.
"""

from __future__ import annotations

import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from lablink_allocator_service.conf.structured_config import Config

from lablink_cli.auth.credentials import get_session

console = Console()


# ------------------------------------------------------------------
# Step 1: Validate AWS credentials
# ------------------------------------------------------------------
def check_credentials(session: boto3.Session) -> dict:
    """Validate AWS credentials and return caller identity."""
    sts = session.client("sts")
    try:
        identity = sts.get_caller_identity()
        return {
            "account": identity["Account"],
            "arn": identity["Arn"],
            "user_id": identity["UserId"],
        }
    except (ClientError, Exception) as e:
        console.print(
            "[red]AWS credentials not found or invalid.[/red]"
        )
        console.print()
        console.print(
            "  To create access keys, visit:"
        )
        console.print(
            "  [link=https://console.aws.amazon.com/iam/"
            "home#/security_credentials]"
            "https://console.aws.amazon.com/iam/"
            "home#/security_credentials"
            "[/link]"
        )
        console.print()
        console.print(
            "  Then configure them with one of:"
        )
        console.print(
            '  [dim]1. Run: [bold]aws configure[/bold]'
            "[/dim]"
        )
        console.print(
            "  [dim]2. Set environment variables: "
            "[bold]AWS_ACCESS_KEY_ID[/bold] and "
            "[bold]AWS_SECRET_ACCESS_KEY[/bold][/dim]"
        )
        console.print()
        console.print(f"  [dim]Error: {e}[/dim]")
        raise SystemExit(1)


# ------------------------------------------------------------------
# Step 2: Create S3 bucket for Terraform state
# ------------------------------------------------------------------
def create_s3_bucket(
    session: boto3.Session, bucket_name: str, region: str
) -> bool:
    """Create an S3 bucket with versioning. Returns True if created."""
    s3 = session.client("s3")

    # Check if we already own this bucket
    try:
        s3.head_bucket(Bucket=bucket_name)
        console.print(
            f"  [green]exists[/green] S3 bucket: {bucket_name}"
        )
        return False
    except ClientError:
        # head_bucket returns 403 for both "not yours" and
        # "doesn't exist" (S3 anti-enumeration behavior).
        # Try create_bucket and handle specific errors instead.
        pass

    # Create bucket (us-east-1 doesn't use LocationConstraint)
    create_args: dict = {"Bucket": bucket_name}
    if region != "us-east-1":
        create_args["CreateBucketConfiguration"] = {
            "LocationConstraint": region
        }

    try:
        s3.create_bucket(**create_args)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "BucketAlreadyOwnedByYou":
            console.print(
                f"  [green]exists[/green] S3 bucket: "
                f"{bucket_name}"
            )
            return False
        if code == "BucketAlreadyExists":
            console.print(
                f"  [red]error[/red] S3 bucket "
                f"'{bucket_name}' is taken by another "
                "account — this should not happen with "
                "account-ID-based naming"
            )
            raise SystemExit(1)
        raise

    # Enable versioning
    s3.put_bucket_versioning(
        Bucket=bucket_name,
        VersioningConfiguration={"Status": "Enabled"},
    )
    console.print(
        f"  [green]created[/green] S3 bucket: {bucket_name} "
        "(versioning enabled)"
    )
    return True


# ------------------------------------------------------------------
# Step 3: Create DynamoDB table for Terraform state locking
# ------------------------------------------------------------------
def create_dynamodb_table(
    session: boto3.Session, region: str
) -> bool:
    """Create the lock-table DynamoDB table. Returns True if created."""
    dynamodb = session.client("dynamodb", region_name=region)
    table_name = "lock-table"

    try:
        dynamodb.describe_table(TableName=table_name)
        console.print(
            f"  [green]exists[/green] DynamoDB table: {table_name}"
        )
        return False
    except dynamodb.exceptions.ResourceNotFoundException:
        pass

    dynamodb.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": "LockID", "KeyType": "HASH"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "LockID", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    # Wait for table to become active
    waiter = dynamodb.get_waiter("table_exists")
    waiter.wait(
        TableName=table_name,
        WaiterConfig={"Delay": 2, "MaxAttempts": 30},
    )
    console.print(
        f"  [green]created[/green] DynamoDB table: {table_name}"
    )
    return True


# ------------------------------------------------------------------
# Step 4: Route53 hosted zone (optional)
# ------------------------------------------------------------------
def create_route53_zone(
    session: boto3.Session, domain: str
) -> str | None:
    """Create or find a Route53 hosted zone. Returns zone ID or None."""
    route53 = session.client("route53")

    # Extract root domain (e.g., example.com from test.example.com)
    parts = domain.split(".")
    if len(parts) >= 2:
        zone_name = ".".join(parts[-2:])
    else:
        zone_name = domain

    # Check for existing zone
    resp = route53.list_hosted_zones_by_name(DNSName=zone_name)
    matching = [
        z
        for z in resp["HostedZones"]
        if z["Name"].rstrip(".") == zone_name
    ]

    if len(matching) == 1:
        zone_id = matching[0]["Id"].replace("/hostedzone/", "")
        console.print(
            f"  [green]exists[/green] Route53 zone: "
            f"{zone_name} ({zone_id})"
        )
        return zone_id

    if len(matching) > 1:
        console.print(
            f"  [yellow]warning[/yellow] Multiple zones found "
            f"for {zone_name} — resolve manually"
        )
        return None

    # Create new zone
    caller_ref = f"lablink-setup-{int(time.time())}"
    resp = route53.create_hosted_zone(
        Name=zone_name, CallerReference=caller_ref
    )
    zone_id = resp["HostedZone"]["Id"].replace(
        "/hostedzone/", ""
    )

    # Show nameservers
    zone_info = route53.get_hosted_zone(Id=zone_id)
    nameservers = zone_info["DelegationSet"]["NameServers"]

    console.print(
        f"  [green]created[/green] Route53 zone: "
        f"{zone_name} ({zone_id})"
    )
    console.print()
    console.print(
        Panel(
            "\n".join(f"  {ns}" for ns in nameservers),
            title="[yellow]Update your domain registrar "
            "with these nameservers[/yellow]",
            border_style="yellow",
        )
    )
    return zone_id


# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------
def resolve_bucket_name(account_id: str) -> str:
    """Generate a unique bucket name using the AWS account ID."""
    return f"lablink-tf-state-{account_id}"


def run_setup(cfg: Config, config_path: Path | None = None) -> None:
    """Run the full setup sequence."""
    region = cfg.app.region

    console.print()
    console.print(
        Panel(
            "[bold]LabLink Setup — Remote State[/bold]\n"
            "Creates S3 + DynamoDB for Terraform state.",
            border_style="cyan",
        )
    )
    console.print()

    # Step 1: Credentials
    console.print("[bold]Step 1/3:[/bold] Checking AWS credentials")
    session = get_session(region=region)
    identity = check_credentials(session)
    console.print(
        f"  [green]authenticated[/green] "
        f"Account: {identity['account']}, "
        f"Identity: {identity['arn']}"
    )
    console.print()

    # Resolve bucket name from account ID
    bucket_name = resolve_bucket_name(identity["account"])

    # Step 2: S3
    console.print(
        "[bold]Step 2/3:[/bold] S3 bucket for Terraform state"
    )
    create_s3_bucket(session, bucket_name, region)
    console.print()

    # Step 3: DynamoDB
    console.print(
        "[bold]Step 3/3:[/bold] DynamoDB table for state locking"
    )
    create_dynamodb_table(session, region)

    # Persist bucket_name to user config
    cfg.bucket_name = bucket_name
    from lablink_cli.config.schema import save_config

    if config_path is None:
        from lablink_cli.app import DEFAULT_CONFIG

        config_path = DEFAULT_CONFIG

    save_config(cfg, config_path)
    console.print(
        f"  [green]saved[/green] bucket_name → {config_path}"
    )
    console.print()

    # Optional: Route53
    if cfg.dns.enabled and cfg.dns.terraform_managed:
        console.print(
            "[bold]Optional:[/bold] Route53 hosted zone"
        )
        zone_id = create_route53_zone(session, cfg.dns.domain)
        if zone_id and not cfg.dns.zone_id:
            console.print(
                f"  [dim]Tip: set dns.zone_id to "
                f"'{zone_id}' in your config[/dim]"
            )
        console.print()

    # Summary
    summary = Table(title="Setup Complete", show_header=False)
    summary.add_column("Resource", style="bold")
    summary.add_column("Value")
    summary.add_row("Region", region)
    summary.add_row("S3 Bucket", bucket_name)
    summary.add_row("DynamoDB Table", "lock-table")
    summary.add_row("AWS Account", identity["account"])
    console.print(summary)
    console.print()
    console.print(
        "[dim]Next step:[/dim] "
        "[bold]lablink deploy[/bold]"
    )
