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
    DNS can be disabled entirely, or configured with different naming patterns.

    Attributes:
        enabled (bool): Whether DNS is enabled. If False, only IP addresses are used.
        domain (str): The base domain name (e.g., "sleap.ai").
        app_name (str): The application name used in subdomains (e.g., "lablink").
        pattern (str): Naming pattern for DNS records. Options:
            - "auto": Automatically generate based on environment
                      prod: {app_name}.{domain}
                      non-prod: {env}.{app_name}.{domain}
            - "app-only": Always use {app_name}.{domain}
            - "custom": Use custom_subdomain value
        custom_subdomain (str): Custom subdomain when pattern="custom"
        create_zone (bool): Whether to create a new Route 53 hosted zone
    """

    enabled: bool = field(default=False)
    domain: str = field(default="")
    app_name: str = field(default="lablink")
    pattern: str = field(default="auto")
    custom_subdomain: str = field(default="")
    create_zone: bool = field(default=False)


@dataclass
class Config:
    """Configuration for the LabLink Allocator Service.
    This class aggregates the database, machine, and application configurations.

    Attributes:
        db (DatabaseConfig): The database configuration.
        machine (MachineConfig): The machine configuration.
        app (AppConfig): The application configuration.
        dns (DNSConfig): The DNS configuration.
        bucket_name (str): The S3 bucket name for Terraform state.
    """

    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    machine: MachineConfig = field(default_factory=MachineConfig)
    app: AppConfig = field(default_factory=AppConfig)
    dns: DNSConfig = field(default_factory=DNSConfig)
    bucket_name: str = field(default="tf-state-lablink-allocator-bucket")


cs = ConfigStore.instance()
cs.store(name="config", node=Config)
