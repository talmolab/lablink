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

    def test_version_long_flag(self):
        from importlib.metadata import version

        from lablink_cli import TEMPLATE_VERSION

        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        out = _plain(result.output)
        assert f"lablink-cli {version('lablink-cli')}" in out
        assert f"lablink-template {TEMPLATE_VERSION.lstrip('v')}" in out

    def test_version_short_flag(self):
        from lablink_cli import TEMPLATE_VERSION

        result = runner.invoke(app, ["-v"])
        assert result.exit_code == 0
        out = _plain(result.output)
        assert "lablink-cli" in out
        assert f"lablink-template {TEMPLATE_VERSION.lstrip('v')}" in out

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

    def test_help_groups_commands_into_panels(self):
        """Top-level --help groups commands under the four Option-A panels."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        out = _plain(result.output)
        for panel in ("Setup", "Deployment", "Operations", "Maintenance"):
            assert panel in out, (
                f"expected panel heading {panel!r} in --help output"
            )


class TestCacheClear:
    def test_cache_clear_command_exists(self):
        result = runner.invoke(app, ["cache-clear", "--help"])
        assert result.exit_code == 0
        assert "cache" in _plain(result.output).lower()

    def test_cache_clear_no_cache_dir(self, tmp_path):
        nonexistent = tmp_path / "nonexistent"
        with patch(
            "lablink_cli.terraform_source.CACHE_DIR", nonexistent
        ):
            result = runner.invoke(app, ["cache-clear"])
        assert result.exit_code == 0
        assert "no cache" in _plain(result.output).lower()

    def test_cache_clear_empty_dir(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        with patch(
            "lablink_cli.terraform_source.CACHE_DIR", cache_dir
        ):
            result = runner.invoke(app, ["cache-clear"])
        assert result.exit_code == 0
        assert "empty" in _plain(result.output).lower()

    def test_cache_clear_removes_versions(self, tmp_path):
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        (cache_dir / "v0.1.0").mkdir()
        (cache_dir / "v0.1.0" / "main.tf").write_text("# tf")
        (cache_dir / "v0.1.1").mkdir()
        (cache_dir / "v0.1.1" / "main.tf").write_text("# tf")

        with patch(
            "lablink_cli.terraform_source.CACHE_DIR", cache_dir
        ):
            result = runner.invoke(app, ["cache-clear"])
        assert result.exit_code == 0
        output = _plain(result.output).lower()
        assert "v0.1.0" in output
        assert "v0.1.1" in output
        assert "cleared 2" in output
        assert not cache_dir.exists()

    # --- --deployments flag (issue #317) ---

    def test_cache_clear_deployments_no_dir(self, tmp_path):
        """--deployments with non-existent cache dir exits cleanly."""
        nonexistent = tmp_path / "nonexistent"
        with patch(
            "lablink_cli.deployment_metrics.DEPLOYMENTS_DIR", nonexistent
        ):
            result = runner.invoke(
                app, ["cache-clear", "--deployments"]
            )
        assert result.exit_code == 0

    def test_cache_clear_deployments_empty_dir(self, tmp_path):
        """--deployments with empty cache dir exits cleanly."""
        dep_dir = tmp_path / "deployments"
        dep_dir.mkdir()
        with patch(
            "lablink_cli.deployment_metrics.DEPLOYMENTS_DIR", dep_dir
        ):
            result = runner.invoke(
                app, ["cache-clear", "--deployments"]
            )
        assert result.exit_code == 0
        assert "empty" in _plain(result.output).lower()

    def test_cache_clear_deployments_removes_records(self, tmp_path):
        """--deployments deletes every *.json file in the cache."""
        dep_dir = tmp_path / "deployments"
        dep_dir.mkdir()
        (dep_dir / "mylab-2026-04-13.json").write_text('{"x":1}')
        (dep_dir / "mylab-2026-04-14.json").write_text('{"x":2}')

        with patch(
            "lablink_cli.deployment_metrics.DEPLOYMENTS_DIR", dep_dir
        ):
            result = runner.invoke(
                app, ["cache-clear", "--deployments"]
            )
        assert result.exit_code == 0
        assert list(dep_dir.glob("*.json")) == []
        assert "cleared 2" in _plain(result.output).lower()

    def test_cache_clear_deployments_does_not_touch_terraform(
        self, tmp_path
    ):
        """--deployments should leave the Terraform template cache alone."""
        tf_dir = tmp_path / "tf"
        tf_dir.mkdir()
        (tf_dir / "v0.1.0").mkdir()
        (tf_dir / "v0.1.0" / "main.tf").write_text("# tf")

        dep_dir = tmp_path / "deployments"
        dep_dir.mkdir()
        (dep_dir / "mylab.json").write_text('{"x":1}')

        with (
            patch("lablink_cli.terraform_source.CACHE_DIR", tf_dir),
            patch(
                "lablink_cli.deployment_metrics.DEPLOYMENTS_DIR", dep_dir
            ),
        ):
            result = runner.invoke(
                app, ["cache-clear", "--deployments"]
            )

        assert result.exit_code == 0
        # Terraform cache untouched
        assert (tf_dir / "v0.1.0" / "main.tf").exists()
        # Deployment cache wiped
        assert list(dep_dir.glob("*.json")) == []

    def test_cache_clear_default_does_not_touch_deployments(
        self, tmp_path
    ):
        """Bare `cache-clear` preserves the deployments cache (backwards compat)."""
        tf_dir = tmp_path / "tf"
        tf_dir.mkdir()
        (tf_dir / "v0.1.0").mkdir()
        (tf_dir / "v0.1.0" / "main.tf").write_text("# tf")

        dep_dir = tmp_path / "deployments"
        dep_dir.mkdir()
        (dep_dir / "mylab.json").write_text('{"x":1}')

        with (
            patch("lablink_cli.terraform_source.CACHE_DIR", tf_dir),
            patch(
                "lablink_cli.deployment_metrics.DEPLOYMENTS_DIR", dep_dir
            ),
        ):
            result = runner.invoke(app, ["cache-clear"])

        assert result.exit_code == 0
        # Deployment cache untouched
        assert (dep_dir / "mylab.json").exists()

    def test_cache_clear_all_removes_both(self, tmp_path):
        """--all clears both the Terraform and deployment caches."""
        tf_dir = tmp_path / "tf"
        tf_dir.mkdir()
        (tf_dir / "v0.1.0").mkdir()
        (tf_dir / "v0.1.0" / "main.tf").write_text("# tf")

        dep_dir = tmp_path / "deployments"
        dep_dir.mkdir()
        (dep_dir / "mylab.json").write_text('{"x":1}')

        with (
            patch("lablink_cli.terraform_source.CACHE_DIR", tf_dir),
            patch(
                "lablink_cli.deployment_metrics.DEPLOYMENTS_DIR", dep_dir
            ),
        ):
            result = runner.invoke(app, ["cache-clear", "--all"])

        assert result.exit_code == 0
        assert not tf_dir.exists()
        assert list(dep_dir.glob("*.json")) == []

    # --- --stale flag (issue #317 follow-up) ---

    def test_cache_clear_deployments_stale_removes_only_in_progress(
        self, tmp_path
    ):
        """--deployments --stale deletes in_progress records; keeps success/failed."""
        dep_dir = tmp_path / "deployments"
        dep_dir.mkdir()
        (dep_dir / "a.json").write_text('{"status": "in_progress"}')
        (dep_dir / "b.json").write_text('{"status": "success"}')
        (dep_dir / "c.json").write_text('{"status": "failed"}')
        (dep_dir / "d.json").write_text('{"status": "in_progress"}')
        # Malformed JSON is un-promotable by definition → treated as stale.
        (dep_dir / "e.json").write_text("{not json")

        with patch(
            "lablink_cli.deployment_metrics.DEPLOYMENTS_DIR", dep_dir
        ):
            result = runner.invoke(
                app, ["cache-clear", "--deployments", "--stale"]
            )

        assert result.exit_code == 0
        remaining = {p.name for p in dep_dir.glob("*.json")}
        assert remaining == {"b.json", "c.json"}
        assert "3 stale" in _plain(result.output).lower()

    def test_cache_clear_deployments_stale_no_matches(self, tmp_path):
        """--stale with only success/failed records exits cleanly, deletes nothing."""
        dep_dir = tmp_path / "deployments"
        dep_dir.mkdir()
        (dep_dir / "a.json").write_text('{"status": "success"}')
        (dep_dir / "b.json").write_text('{"status": "failed"}')

        with patch(
            "lablink_cli.deployment_metrics.DEPLOYMENTS_DIR", dep_dir
        ):
            result = runner.invoke(
                app, ["cache-clear", "--deployments", "--stale"]
            )

        assert result.exit_code == 0
        assert {p.name for p in dep_dir.glob("*.json")} == {
            "a.json",
            "b.json",
        }
        assert "no stale" in _plain(result.output).lower()

    def test_cache_clear_stale_without_deployments_warns(self, tmp_path):
        """--stale alone (no --deployments) should warn and still clear tf cache."""
        tf_dir = tmp_path / "tf"
        tf_dir.mkdir()
        (tf_dir / "v0.1.0").mkdir()
        (tf_dir / "v0.1.0" / "main.tf").write_text("# tf")

        with patch("lablink_cli.terraform_source.CACHE_DIR", tf_dir):
            result = runner.invoke(app, ["cache-clear", "--stale"])

        assert result.exit_code == 0
        assert "no effect" in _plain(result.output).lower()
        assert not tf_dir.exists()


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
