from hydra.core.config_store import ConfigStore
from dataclasses import dataclass, field


@dataclass
class DatabaseConfig:
    dbname: str = field(default="lablink_db")
    user: str = field(default="lablink")
    password: str = field(default="lablink")
    host: str = field(default="localhost")
    port: int = field(default=5432)
    table_name: str = field(default="vms")


@dataclass
class Config:
    db: DatabaseConfig = field(default_factory=DatabaseConfig)


cs = ConfigStore.instance()
cs.store(name="config", node=Config)
