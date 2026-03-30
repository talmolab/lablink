"""Tests for lablink_cli.commands.doctor pre-flight checks."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from lablink_cli.commands.doctor import (
    _check_ami,
    _check_terraform,
)


# ------------------------------------------------------------------
# _check_terraform
# ------------------------------------------------------------------
class TestCheckTerraform:
    @patch("shutil.which", return_value=None)
    def test_not_installed(self, _mock_which):
        result = _check_terraform()
        assert result["status"] == "fail"
        assert "not found" in result["detail"]

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/terraform")
    def test_installed_with_version(self, _mock_which, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"terraform_version": "1.6.6"}),
        )

        result = _check_terraform()
        assert result["status"] == "pass"
        assert "1.6.6" in result["detail"]

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/terraform")
    def test_version_check_fails(self, _mock_which, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        result = _check_terraform()
        assert result["status"] == "warn"

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/terraform")
    def test_timeout(self, _mock_which, mock_run):
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired("terraform", 10)

        result = _check_terraform()
        assert result["status"] == "warn"


# ------------------------------------------------------------------
# _check_ami
# ------------------------------------------------------------------
class TestCheckAmi:
    def test_no_config(self):
        result = _check_ami(None)
        assert result["status"] == "warn"

    def test_supported_region(self):
        cfg = MagicMock()
        cfg.app.region = "us-east-1"
        result = _check_ami(cfg)
        assert result["status"] == "pass"
        assert "ami-" in result["detail"]

    def test_unsupported_region(self):
        cfg = MagicMock()
        cfg.app.region = "ap-south-1"
        result = _check_ami(cfg)
        assert result["status"] == "fail"
        assert "No AMI" in result["detail"]
