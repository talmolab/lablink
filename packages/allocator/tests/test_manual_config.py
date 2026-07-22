"""Unit tests for ManualConfig (connectivity selection for the manual provider)."""

from lablink_allocator_service.conf.structured_config import Config, ManualConfig


class TestManualConfig:
    def test_manual_config_defaults(self):
        config = ManualConfig()
        assert config.connectivity == "lan_direct"
        assert config.overlay_tailnet == ""

    def test_manual_config_mesh_overlay(self):
        config = ManualConfig(
            connectivity="mesh_overlay",
            overlay_tailnet="example.ts.net",
        )
        assert config.connectivity == "mesh_overlay"
        assert config.overlay_tailnet == "example.ts.net"

    def test_config_has_manual_field(self):
        cfg = Config()
        assert isinstance(cfg.manual, ManualConfig)
        assert cfg.manual.connectivity == "lan_direct"

    def test_manual_config_participant_exposure_default(self):
        config = ManualConfig()
        assert config.participant_exposure == "none"

    def test_manual_config_participant_exposure_tailscale_funnel(self):
        config = ManualConfig(
            participant_exposure="tailscale_funnel",
            overlay_tailnet="example.ts.net",
        )
        assert config.participant_exposure == "tailscale_funnel"
