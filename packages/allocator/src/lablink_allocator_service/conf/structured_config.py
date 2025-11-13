"""This module defines the database configuration structure for the LabLink
Allocator Service.
"""

from dataclasses import dataclass, field
from typing import Optional

from hydra.core.config_store import ConfigStore


@dataclass
class DatabaseConfig:
    """Configuration for the database used in the LabLink Allocator Service.
    This class defines the connection parameters for the database, including
    the name, user, password, host, port, table name, and message channel.

    Attributes:
        dbname (str): The name of the database.
        user (str): The username for the database.
        password (str): The password for the database.
        host (str): The host where the database is located.
        port (int): The port on which the database is running.
        table_name (str): The name of the table to store VM information.
        message_channel (str): The name of the message channel for updates.
    """

    dbname: str = field(default="lablink_db")
    user: str = field(default="lablink")
    password: str = field(default="lablink")
    host: str = field(default="localhost")
    port: int = field(default=5432)
    table_name: str = field(default="vm_table")
    message_channel: str = field(default="vm_updates")


@dataclass
class AppConfig:
    """Configuration for the LabLink Allocator Service application.

    Attributes:
        admin_user (str): The username for the admin user.
        admin_password (str): The password for the admin user.
        region (str): The AWS region where the service is deployed.
    """

    admin_user: str = field(default="admin")
    admin_password: str = field(default="admin_password")
    region: str = field(default="us-west-2")


@dataclass
class MachineConfig:
    """Configuration for the machine used in the LabLink Allocator Service.
    This class defines the machine type, repository, image, AMI ID, and
    software to be used.

    Attributes:
        machine_type (str): The type of the machine to be used.
        repository (Optional[str]): The repository URL for the machine image.
        image (str): The Docker image ID to be used for the machine.
        ami_id (str): The Amazon Machine Image (AMI) ID for the machine.
        software (str): The software to be installed on the machine.
        extension (str): The file extension associated with the software.
    """

    machine_type: str = field(default="g4dn.xlarge")
    repository: Optional[str] = field(default=None)
    image: str = field(default="ghcr.io/talmolab/lablink-client-base-image:latest")
    ami_id: str = field(default="ami-00c257e12d6828491")
    software: str = field(default="sleap")
    extension: str = field(default="slp")


@dataclass
class DNSConfig:
    """Configuration for DNS and domain setup.

    This class defines DNS settings for Route 53 hosted zones and records.
    DNS can be disabled entirely, or configured with external DNS providers.

    Attributes:
        enabled (bool): Whether DNS is enabled. If False, only IP addresses are used.
        terraform_managed (bool): Whether Terraform creates/destroys DNS records.
            - True: Terraform manages Route53 DNS records (creates and destroys)
            - False: External DNS management (CloudFlare, manual Route53, etc.)
        domain (str): Full domain name for the allocator (e.g., "lablink.sleap.ai", "test.lablink.sleap.ai").
            Required when enabled=true. Supports sub-subdomains for environment separation.
        zone_id (str): Optional Route53 hosted zone ID. If provided, skips zone lookup.
            Use this when zone lookup finds the wrong zone (e.g., parent vs subdomain).
    """

    enabled: bool = field(default=False)
    terraform_managed: bool = field(default=True)
    domain: str = field(default="")
    zone_id: str = field(default="")


@dataclass
class EIPConfig:
    """Configuration for Elastic IP management strategy.

    Attributes:
        strategy (str): EIP allocation strategy. Options:
            - "persistent": Reuse existing tagged EIP across deployments
            - "dynamic": Create new EIP for each deployment
        tag_name (str): Name tag value to identify reusable EIPs
    """

    strategy: str = field(default="dynamic")
    tag_name: str = field(default="lablink-eip")


@dataclass
class SSLConfig:
    """Configuration for SSL/TLS certificate management.

    Attributes:
        provider (str): SSL provider. Options:
            - "none": HTTP only, no SSL
            - "letsencrypt": Automatic SSL via Caddy + Let's Encrypt
            - "cloudflare": CloudFlare proxy handles SSL (requires terraform_managed=false)
            - "acm": AWS Certificate Manager (requires ALB, certificate_arn)
        email (str): Email address for Let's Encrypt notifications (required when provider="letsencrypt")
        certificate_arn (str): AWS ACM certificate ARN (required when provider="acm")
    """

    provider: str = field(default="letsencrypt")
    email: str = field(default="")
    certificate_arn: str = field(default="")


@dataclass
class AllocatorConfig:
    """Configuration for allocator service deployment.

    This section is used by infrastructure deployment (Terraform) to specify
    which Docker image tag to use for the allocator service. The allocator
    service itself doesn't use this field, but it must be present in the
    schema to accept infrastructure configuration files.

    Attributes:
        image_tag (str): Docker image tag for the allocator service.
            Examples: "linux-amd64-latest-test", "linux-amd64-v1.2.3"
    """

    image_tag: str = field(default="linux-amd64-latest")


@dataclass
class StartupConfig:
    """Configuration for startup behavior of the allocator service.
    Attributes:
        enabled (bool): Whether startup script execution is enabled.
        path (str): Path to the startup script to be executed.
        on_error (str): Behavior on startup script error. Options:
            - "continue": Log the error and continue startup.
            - "fail": Abort startup on error.
    """

    enabled: bool = field(default=False)
    path: str = field(default="")
    on_error: str = field(default="continue")  # Options: "continue", "fail"


@dataclass
class Config:
    """Configuration for the LabLink Allocator Service.
    This class aggregates the database, machine, and application configurations.

    Attributes:
        db (DatabaseConfig): The database configuration.
        machine (MachineConfig): The machine configuration.
        app (AppConfig): The application configuration.
        dns (DNSConfig): The DNS configuration.
        eip (EIPConfig): The EIP management configuration.
        ssl (SSLConfig): The SSL certificate configuration.
        allocator (AllocatorConfig): The allocator deployment configuration.
        bucket_name (str): The S3 bucket name for Terraform state.
    """

    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    machine: MachineConfig = field(default_factory=MachineConfig)
    app: AppConfig = field(default_factory=AppConfig)
    dns: DNSConfig = field(default_factory=DNSConfig)
    eip: EIPConfig = field(default_factory=EIPConfig)
    ssl: SSLConfig = field(default_factory=SSLConfig)
    allocator: AllocatorConfig = field(default_factory=AllocatorConfig)
    bucket_name: str = field(default="tf-state-lablink-allocator-bucket")
    startup_script: StartupConfig = field(default_factory=StartupConfig)


cs = ConfigStore.instance()
cs.store(name="config", node=Config)
