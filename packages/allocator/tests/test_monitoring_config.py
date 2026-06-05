"""MonitoringConfig defaults and structure."""

from omegaconf import OmegaConf

from lablink_allocator_service.conf.structured_config import (
    Config,
    MonitoringConfig,
)


def test_monitoring_defaults_disabled():
    cfg = MonitoringConfig()
    assert cfg.enabled is False
    assert cfg.subject_window_patterns == []
    assert cfg.process_allowlist == [
        "sleap-train",
        "sleap-track",
        "sleap-label",
    ]
    assert cfg.watch_dir == "/home/client/Desktop"
    assert cfg.sample_interval_seconds == 2
    assert cfg.push_interval_seconds == 60


def test_config_includes_monitoring_field():
    cfg = Config()
    assert isinstance(cfg.monitoring, MonitoringConfig)
    assert cfg.monitoring.enabled is False


def test_monitoring_block_loads_from_yaml():
    raw = {
        "monitoring": {
            "enabled": True,
            "subject_window_patterns": ["deeplabcut"],
            "process_allowlist": ["custom-train"],
            "watch_dir": "/tmp/work",
            "sample_interval_seconds": 3,
            "push_interval_seconds": 30,
        }
    }
    schema = OmegaConf.structured(Config)
    merged = OmegaConf.merge(schema, OmegaConf.create(raw))
    assert merged.monitoring.enabled is True
    assert merged.monitoring.subject_window_patterns == ["deeplabcut"]
    assert merged.monitoring.process_allowlist == ["custom-train"]
    assert merged.monitoring.sample_interval_seconds == 3
