"""Tests for lablink_cli.app CLI entry point."""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import typer
from typer.testing import CliRunner

from lablink_cli.app import _load_cfg, app

runner = CliRunner()

# Strip ANSI escape codes from output (rich adds them in CI)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI_RE.sub("", text)


# ------------------------------------------------------------------
# _load_cfg
# ------------------------------------------------------------------
class TestLoadCfg:
    def test_missing_config_exits(self, tmp_path):
        missing_path = str(tmp_path / "nonexistent.yaml")
        with pytest.raises(typer.Exit):
            _load_cfg(missing_path)

    @patch("lablink_cli.config.schema.load_config")
    def test_loads_existing_config(self, mock_load, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("deployment_name: test")
        mock_load.return_value = MagicMock()

        _load_cfg(str(config_path))
        mock_load.assert_called_once_with(config_path)

    @patch("lablink_cli.app.DEFAULT_CONFIG", new=Path("/tmp/test-lablink/config.yaml"))
    def test_default_path_when_none(self):
        with pytest.raises(typer.Exit):
            _load_cfg(None)


# ------------------------------------------------------------------
# CLI commands (smoke tests via typer runner)
# ------------------------------------------------------------------
class TestCLICommands:
    def test_help(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        out = _plain(result.output).lower()
        assert "lablink" in out or "deploy" in out

    def test_doctor_command_exists(self):
        result = runner.invoke(app, ["doctor", "--help"])
        assert result.exit_code == 0
        out = _plain(result.output).lower()
        assert "prerequisites" in out or "check" in out

    def test_deploy_command_exists(self):
        result = runner.invoke(app, ["deploy", "--help"])
        assert result.exit_code == 0

    def test_destroy_command_exists(self):
        result = runner.invoke(app, ["destroy", "--help"])
        assert result.exit_code == 0

    def test_status_command_exists(self):
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0

    def test_cleanup_command_exists(self):
        result = runner.invoke(app, ["cleanup", "--help"])
        assert result.exit_code == 0
        assert "dry-run" in _plain(result.output)

    def test_show_config_command_exists(self):
        result = runner.invoke(app, ["show-config", "--help"])
        assert result.exit_code == 0

    def test_configure_command_exists(self):
        result = runner.invoke(app, ["configure", "--help"])
        assert result.exit_code == 0

    def test_setup_command_exists(self):
        result = runner.invoke(app, ["setup", "--help"])
        assert result.exit_code == 0

    def test_launch_client_command_exists(self):
        result = runner.invoke(app, ["launch-client", "--help"])
        assert result.exit_code == 0
        assert "num-vms" in _plain(result.output)

    def test_logs_command_exists(self):
        result = runner.invoke(app, ["logs", "--help"])
        assert result.exit_code == 0

    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        assert result.exit_code in (0, 2)
        out = _plain(result.output).lower()
        assert "deploy" in out or "usage" in out


class TestShowConfig:
    def test_show_config_missing_file(self, tmp_path):
        result = runner.invoke(
            app, ["show-config", "--config", str(tmp_path / "missing.yaml")]
        )
        assert result.exit_code == 1

    @patch("lablink_cli.config.schema.validate_config")
    @patch("lablink_cli.config.schema.load_config")
    def test_show_config_valid(self, mock_load, mock_validate, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("deployment_name: test\nenvironment: dev\n")
        mock_load.return_value = MagicMock()
        mock_validate.return_value = []

        result = runner.invoke(
            app, ["show-config", "--config", str(config_path)]
        )
        assert result.exit_code == 0
