"""This module defines the allocator configuration structure for the Lablink Client Service."""

from hydra.core.config_store import ConfigStore
from dataclasses import dataclass, field


@dataclass
class AllocatorConfig:
    host: str = field(default="localhost")
    port: int = field(default=5000)


@dataclass
class ClientConfig:
    software: str = field(default="sleap")


@dataclass
class Config:
    allocator: AllocatorConfig = field(default_factory=AllocatorConfig)
    client: ClientConfig = field(default_factory=ClientConfig)


cs = ConfigStore.instance()
cs.store(name="config", node=Config)
