"""Client-side MonitoringConfig defaults."""

from lablink_client_service.conf.structured_config import (
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
