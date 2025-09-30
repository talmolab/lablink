"""This module defines the database configuration structure for the LabLink Allocator Service."""

from dataclasses import dataclass, field
from typing import Optional

from hydra.core.config_store import ConfigStore


@dataclass
class DatabaseConfig:
    """Configuration for the database used in the LabLink Allocator Service.
    This class defines the connection parameters for the database, including the name, user,
    password, host, port, table name, and message channel.

    Attributes:
        dbname (str): The name of the database.
        user (str): The username for the database.
        password (str): The password for the database.
        host (str): The host where the database is located.
        port (int): The port on which the database is running.
        table_name (str): The name of the table to store VM information.
        message_channel (str): The name of the message channel for updates.
    """

    dbname: str = field(default="lablink")
    user: str = field(default="lablink")
    password: str = field(default="lablink_password")
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
    This class defines the machine type, repository, image, AMI ID, and software to be used.

    Attributes:
        machine_type (str): The type of the machine to be used.
        repository (Optional[str]): The repository URL for the machine image.
        image (str): The Docker image ID to be used for the machine.
        ami_id (str): The Amazon Machine Image (AMI) ID for the machine.
        software (str): The software to be installed on the machine.
    """

    machine_type: str = field(default="g4dn.xlarge")
    repository: Optional[str] = field(default=None)
    image: str = field(default="ghcr.io/talmolab/lablink-client-base-image:latest")
    ami_id: str = field(default="ami-00c257e12d6828491")
    software: str = field(default="sleap")


@dataclass
class Config:
    """Configuration for the LabLink Allocator Service.
    This class aggregates the database, machine, and application configurations.

    Attributes:
        db (DatabaseConfig): The database configuration.
        machine (MachineConfig): The machine configuration.
        app (AppConfig): The application configuration.
        bucket_name (str): The S3 bucket name for Terraform state.
    """

    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    machine: MachineConfig = field(default_factory=MachineConfig)
    app: AppConfig = field(default_factory=AppConfig)
    bucket_name: str = field(default="tf-state-lablink-allocator-bucket")


cs = ConfigStore.instance()
cs.store(name="config", node=Config)
