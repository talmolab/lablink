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
class MonitoringConfig:
    enabled: bool = False
    subject_window_patterns: list[str] = field(default_factory=list)
    process_allowlist: list[str] = field(
        default_factory=lambda: [
            "sleap-train",
            "sleap-track",
            "sleap-label",
        ]
    )
    watch_dir: str = "/home/client/Desktop"
    sample_interval_seconds: int = 2
    push_interval_seconds: int = 60


@dataclass
class Config:
    allocator: AllocatorConfig = field(default_factory=AllocatorConfig)
    client: ClientConfig = field(default_factory=ClientConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)


cs = ConfigStore.instance()
cs.store(name="config", node=Config)
