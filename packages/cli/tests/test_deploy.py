"""Tests for lablink_cli.commands.deploy Terraform orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lablink_cli.api import (
    AllocatorAuthError,
    AllocatorNotFoundError,
    AllocatorUnavailableError,
)
from lablink_cli.commands.deploy import (
    _destroy_client_vms,
    _poll_allocator_health,
    _prepare_working_dir,
    _run_terraform,
    _terraform_destroy,
)


# ------------------------------------------------------------------
# _prepare_working_dir
# ------------------------------------------------------------------
class TestPrepareWorkingDir:
    @patch("lablink_cli.commands.deploy.get_terraform_files")
    @patch("lablink_cli.commands.deploy.get_deploy_dir")
    @patch("lablink_cli.commands.deploy.save_config")
    def test_creates_directory(
        self, mock_save, mock_deploy_dir, mock_get_tf, mock_cfg, tmp_path
    ):
        deploy_dir = tmp_path / "deploy"
        mock_deploy_dir.return_value = deploy_dir

        # Simulate cached terraform files
        tf_cache = tmp_path / "tf_cache"
        tf_cache.mkdir()
        (tf_cache / "main.tf").write_text('variable "region" {}')
        (tf_cache / "variables.tf").write_text("# variables")
        (tf_cache / "user_data.sh").write_text("#!/bin/bash")
        mock_get_tf.return_value = tf_cache

        result = _prepare_working_dir(mock_cfg)
        assert result == deploy_dir
        assert (deploy_dir / "config").exists()
        assert (deploy_dir / "main.tf").exists()
        assert (deploy_dir / "user_data.sh").exists()

    @patch("lablink_cli.commands.deploy.get_terraform_files")
    @patch("lablink_cli.commands.deploy.get_deploy_dir")
    @patch("lablink_cli.commands.deploy.save_config")
    def test_copies_hcl_files(
        self, mock_save, mock_deploy_dir, mock_get_tf, mock_cfg, tmp_path
    ):
        deploy_dir = tmp_path / "deploy"
        mock_deploy_dir.return_value = deploy_dir

        tf_cache = tmp_path / "tf_cache"
        tf_cache.mkdir()
        (tf_cache / "main.tf").write_text('variable "region" {}')
        (tf_cache / "backend-dev.hcl").write_text("# dev")
        mock_get_tf.return_value = tf_cache

        result = _prepare_working_dir(mock_cfg)
        assert (result / "backend-dev.hcl").exists()

    @patch("lablink_cli.commands.deploy.get_terraform_files")
    @patch("lablink_cli.commands.deploy.get_deploy_dir")
    @patch("lablink_cli.commands.deploy.save_config")
    def test_no_region_string_replacement(
        self, mock_save, mock_deploy_dir, mock_get_tf, mock_cfg, tmp_path
    ):
        """Region should NOT be string-replaced in main.tf."""
        deploy_dir = tmp_path / "deploy"
        mock_deploy_dir.return_value = deploy_dir
        mock_cfg.app.region = "eu-west-1"

        tf_cache = tmp_path / "tf_cache"
        tf_cache.mkdir()
        (tf_cache / "main.tf").write_text(
            'provider "aws" {\n  region = var.region\n}'
        )
        mock_get_tf.return_value = tf_cache

        result = _prepare_working_dir(mock_cfg)
        content = (result / "main.tf").read_text()
        # File should be unchanged — region is passed via -var, not replaced
        assert "var.region" in content
        assert "eu-west-1" not in content


# ------------------------------------------------------------------
# _run_terraform
# ------------------------------------------------------------------
class TestRunTerraform:
    @patch("subprocess.Popen")
    def test_success(self, mock_popen, tmp_path):
        proc = MagicMock()
        proc.stdout = iter(["Initializing...\n", "Complete!\n"])
        proc.wait.return_value = None
        proc.returncode = 0
        mock_popen.return_value = proc

        returncode = _run_terraform(["init"], cwd=tmp_path)
        assert returncode == 0
        mock_popen.assert_called_once()

    @patch("subprocess.Popen")
    def test_failure_raises(self, mock_popen, tmp_path):
        proc = MagicMock()
        proc.stdout = iter(["Error!\n"])
        proc.wait.return_value = None
        proc.returncode = 1
        mock_popen.return_value = proc

        with pytest.raises(SystemExit):
            _run_terraform(["apply"], cwd=tmp_path)

    @patch("subprocess.Popen")
    def test_failure_no_check(self, mock_popen, tmp_path):
        proc = MagicMock()
        proc.stdout = iter([])
        proc.wait.return_value = None
        proc.returncode = 1
        mock_popen.return_value = proc

        returncode = _run_terraform(
            ["output"], cwd=tmp_path, check=False
        )
        assert returncode == 1


# ------------------------------------------------------------------
# _destroy_client_vms
# ------------------------------------------------------------------
class TestDestroyClientVms:
    @patch("lablink_cli.commands.deploy.AllocatorAPI")
    @patch(
        "lablink_cli.commands.deploy.get_allocator_url",
        return_value="https://allocator.example.com",
    )
    def test_success(self, mock_url, mock_api_cls, mock_cfg):
        mock_api = MagicMock()
        mock_api.destroy_vms.return_value = {"status": "ok"}
        mock_api_cls.return_value = mock_api

        _destroy_client_vms(mock_cfg, "admin", "pass")
        mock_api.destroy_vms.assert_called_once()

    @patch("lablink_cli.commands.deploy.AllocatorAPI")
    @patch(
        "lablink_cli.commands.deploy.get_allocator_url",
        return_value="https://allocator.example.com",
    )
    def test_auth_error_exits(self, mock_url, mock_api_cls, mock_cfg):
        mock_api = MagicMock()
        mock_api.destroy_vms.side_effect = AllocatorAuthError("401")
        mock_api_cls.return_value = mock_api

        with pytest.raises(SystemExit):
            _destroy_client_vms(mock_cfg, "admin", "pass")

    @patch("lablink_cli.commands.deploy.AllocatorAPI")
    @patch(
        "lablink_cli.commands.deploy.get_allocator_url",
        return_value="https://allocator.example.com",
    )
    def test_unavailable_continues(self, mock_url, mock_api_cls, mock_cfg):
        mock_api = MagicMock()
        mock_api.destroy_vms.side_effect = AllocatorUnavailableError("502")
        mock_api_cls.return_value = mock_api

        _destroy_client_vms(mock_cfg, "admin", "pass")

    @patch("lablink_cli.commands.deploy.AllocatorAPI")
    @patch(
        "lablink_cli.commands.deploy.get_allocator_url",
        return_value="https://allocator.example.com",
    )
    def test_not_found_continues(self, mock_url, mock_api_cls, mock_cfg):
        mock_api = MagicMock()
        mock_api.destroy_vms.side_effect = AllocatorNotFoundError("404")
        mock_api_cls.return_value = mock_api

        _destroy_client_vms(mock_cfg, "admin", "pass")

    @patch(
        "lablink_cli.commands.deploy.get_allocator_url",
        return_value=None,
    )
    def test_no_url_skips(self, mock_url, mock_cfg):
        _destroy_client_vms(mock_cfg, "admin", "pass")


# ------------------------------------------------------------------
# _terraform_destroy
# ------------------------------------------------------------------
class TestTerraformDestroy:
    @patch("lablink_cli.commands.deploy.shutil.rmtree")
    @patch("lablink_cli.commands.deploy._run_terraform")
    @patch("lablink_cli.commands.deploy._terraform_init")
    @patch(
        "lablink_cli.commands.deploy.config_to_dict",
        return_value={"app": {}, "db": {}},
    )
    def test_runs_destroy_sequence(
        self,
        mock_cfg_dict,
        mock_tf_init,
        mock_tf_run,
        mock_rmtree,
        mock_cfg,
        tmp_path,
    ):
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()
        (deploy_dir / "backend.tf").write_text("")
        config_dir = deploy_dir / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("")

        _terraform_destroy(deploy_dir, mock_cfg, "admin", "pass")

        mock_tf_init.assert_called_once_with(deploy_dir, mock_cfg)
        mock_tf_run.assert_called_once()
        mock_rmtree.assert_called_once_with(deploy_dir)


# ------------------------------------------------------------------
# _poll_allocator_health
# ------------------------------------------------------------------
class TestPollAllocatorHealth:
    @patch("lablink_cli.commands.deploy.time")
    @patch("lablink_cli.commands.deploy.check_health_endpoint")
    def test_healthy_on_first_poll(self, mock_check, mock_time):
        """Returns immediately when allocator is healthy on first poll."""
        mock_time.monotonic.side_effect = [0.0, 5.0]
        mock_check.return_value = {
            "status": "pass",
            "healthy": True,
            "uptime_seconds": 30.0,
        }

        result = _poll_allocator_health("http://1.2.3.4:5000", max_wait=120)
        assert result["healthy"] is True
        assert result["elapsed"] == 5.0
        mock_time.sleep.assert_not_called()

    @patch("lablink_cli.commands.deploy.time")
    @patch("lablink_cli.commands.deploy.check_health_endpoint")
    def test_healthy_after_retries(self, mock_check, mock_time):
        """Keeps polling until healthy."""
        # monotonic: start, check1, sleep1, check2, sleep2, check3
        mock_time.monotonic.side_effect = [0.0, 3.0, 4.0, 6.0, 7.0, 9.0]
        mock_check.side_effect = [
            {"status": "unreachable", "healthy": False, "uptime_seconds": None},
            {"status": "starting", "healthy": False, "uptime_seconds": 2.0},
            {"status": "pass", "healthy": True, "uptime_seconds": 8.0},
        ]

        result = _poll_allocator_health("http://1.2.3.4:5000", max_wait=120)
        assert result["healthy"] is True
        assert mock_time.sleep.call_count == 2

    @patch("lablink_cli.commands.deploy.time")
    @patch("lablink_cli.commands.deploy.check_health_endpoint")
    def test_timeout(self, mock_check, mock_time):
        """Returns unhealthy after max_wait exceeded."""
        call_count = 0

        def mock_monotonic():
            nonlocal call_count
            val = call_count * 10.0
            call_count += 1
            return val

        mock_time.monotonic.side_effect = mock_monotonic
        mock_check.return_value = {
            "status": "unreachable",
            "healthy": False,
            "uptime_seconds": None,
        }

        result = _poll_allocator_health("http://1.2.3.4:5000", max_wait=30)
        assert result["healthy"] is False
        assert result["timed_out"] is True
