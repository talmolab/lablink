"""Tests for lablink_cli.commands.deploy Terraform orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from lablink_cli.commands.deploy import (
    _prepare_working_dir,
    _run_terraform,
    run_destroy,
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
# run_destroy — HTTP error handling
# ------------------------------------------------------------------
class TestRunDestroyHttpErrors:
    """Test that run_destroy handles allocator HTTP errors correctly."""

    def _setup_deploy_dir(self, tmp_path):
        """Create a minimal deploy directory."""
        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()
        (deploy_dir / ".terraform").mkdir()
        (deploy_dir / "backend.tf").write_text("")
        config_dir = deploy_dir / "config"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("")
        return deploy_dir

    @patch("lablink_cli.commands.deploy.shutil.rmtree")
    @patch("lablink_cli.commands.deploy._run_terraform")
    @patch("lablink_cli.commands.deploy._terraform_init")
    @patch(
        "lablink_cli.commands.deploy.config_to_dict",
        return_value={"app": {}, "db": {}},
    )
    @patch(
        "lablink_cli.commands.deploy"
        ".resolve_admin_credentials",
        return_value=("admin", "pass"),
    )
    @patch(
        "lablink_cli.commands.deploy.get_allocator_url",
        return_value="https://allocator.example.com",
    )
    @patch("lablink_cli.commands.deploy.get_deploy_dir")
    @patch("lablink_cli.commands.deploy.check_credentials")
    @patch("lablink_cli.commands.deploy._get_session")
    @patch("builtins.input", return_value="yes")
    def test_502_skips_client_destroy(
        self,
        mock_input,
        mock_session,
        mock_creds,
        mock_deploy_dir,
        mock_url,
        mock_admin,
        mock_cfg_dict,
        mock_tf_init,
        mock_tf_run,
        mock_rmtree,
        mock_cfg,
        tmp_path,
    ):
        error = HTTPError(
            "https://allocator.example.com/destroy",
            502,
            "Bad Gateway",
            {},
            None,
        )
        deploy_dir = self._setup_deploy_dir(tmp_path)
        mock_deploy_dir.return_value = deploy_dir

        with patch(
            "urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.side_effect = error
            run_destroy(mock_cfg)

        # Should proceed to terraform destroy
        mock_tf_run.assert_called_once()

    @patch("lablink_cli.commands.deploy._run_terraform")
    @patch("lablink_cli.commands.deploy._terraform_init")
    @patch(
        "lablink_cli.commands.deploy"
        ".resolve_admin_credentials",
        return_value=("admin", "pass"),
    )
    @patch(
        "lablink_cli.commands.deploy.get_allocator_url",
        return_value="https://allocator.example.com",
    )
    @patch("lablink_cli.commands.deploy.get_deploy_dir")
    @patch("lablink_cli.commands.deploy.check_credentials")
    @patch("lablink_cli.commands.deploy._get_session")
    @patch("builtins.input", return_value="yes")
    def test_500_exits(
        self,
        mock_input,
        mock_session,
        mock_creds,
        mock_deploy_dir,
        mock_url,
        mock_admin,
        mock_tf_init,
        mock_tf_run,
        mock_cfg,
        tmp_path,
    ):
        error = HTTPError(
            "https://allocator.example.com/destroy",
            500,
            "Internal Server Error",
            {},
            None,
        )
        deploy_dir = self._setup_deploy_dir(tmp_path)
        mock_deploy_dir.return_value = deploy_dir

        with patch(
            "urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.side_effect = error
            with pytest.raises(SystemExit):
                run_destroy(mock_cfg)

        # Should NOT proceed to terraform destroy
        mock_tf_run.assert_not_called()
