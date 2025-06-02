"""This module defines the database configuration structure for the LabLink Allocator Service."""

from dataclasses import dataclass, field

from hydra.core.config_store import ConfigStore


@dataclass
class DatabaseConfig:
    dbname: str = field(default="lablink")
    user: str = field(default="lablink")
    password: str = field(default="lablink_password")
    host: str = field(default="localhost")
    port: int = field(default=5432)
    table_name: str = field(default="vm_table")
    message_channel: str = field(default="vm_updates")


@dataclass
class AppConfig:
    admin_user: str = field(default="admin")
    admin_password: str = field(default="admin_password")


@dataclass
class Config:
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    app: AppConfig = field(default_factory=AppConfig)


cs = ConfigStore.instance()
cs.store(name="config", node=Config)
