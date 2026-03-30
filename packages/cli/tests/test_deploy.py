"""Tests for lablink_cli.commands.deploy Terraform orchestration."""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lablink_cli.commands.deploy import (
    TERRAFORM_SRC,
    _prepare_working_dir,
    _run_terraform,
)


# ------------------------------------------------------------------
# _prepare_working_dir
# ------------------------------------------------------------------
class TestPrepareWorkingDir:
    @patch("lablink_cli.commands.deploy.TERRAFORM_SRC")
    @patch("lablink_cli.commands.deploy.get_deploy_dir")
    @patch("lablink_cli.commands.deploy.save_config")
    def test_creates_directory(
        self, mock_save, mock_deploy_dir, mock_tf_src, mock_cfg, tmp_path
    ):
        deploy_dir = tmp_path / "deploy"
        mock_deploy_dir.return_value = deploy_dir

        # Set up terraform source dir
        tf_src = tmp_path / "terraform_src"
        tf_src.mkdir()
        (tf_src / "main.tf").write_text('region = "us-west-2"')
        (tf_src / "variables.tf").write_text("# variables")
        (tf_src / "user_data.sh").write_text("#!/bin/bash")

        # Configure the mock to behave like a Path
        mock_tf_src.__truediv__ = lambda self, x: tf_src / x
        mock_tf_src.glob = tf_src.glob

        result = _prepare_working_dir(mock_cfg)
        assert result == deploy_dir
        assert (deploy_dir / "config").exists()

    @patch("lablink_cli.commands.deploy.TERRAFORM_SRC")
    @patch("lablink_cli.commands.deploy.get_deploy_dir")
    @patch("lablink_cli.commands.deploy.save_config")
    def test_region_override(
        self, mock_save, mock_deploy_dir, mock_tf_src, mock_cfg, tmp_path
    ):
        deploy_dir = tmp_path / "deploy"
        mock_deploy_dir.return_value = deploy_dir
        mock_cfg.app.region = "eu-west-1"

        # Set up terraform source
        tf_src = tmp_path / "terraform_src"
        tf_src.mkdir()
        (tf_src / "main.tf").write_text('region = "us-west-2"')

        mock_tf_src.__truediv__ = lambda self, x: tf_src / x
        mock_tf_src.glob = tf_src.glob

        result = _prepare_working_dir(mock_cfg)
        content = (result / "main.tf").read_text()
        assert 'region = "eu-west-1"' in content
        assert 'region = "us-west-2"' not in content


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

        returncode = _run_terraform(["output"], cwd=tmp_path, check=False)
        assert returncode == 1
