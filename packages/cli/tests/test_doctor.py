"""Tests for lablink_cli.commands.doctor pre-flight checks."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


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


# ------------------------------------------------------------------
# _load_config_safe — warn on broken config instead of silent fallback
# ------------------------------------------------------------------
class TestLoadConfigSafe:
    def test_warns_when_config_yaml_is_malformed(
        self, tmp_path, capsys, monkeypatch,
    ):
        """Malformed YAML must surface a yellow warning so the operator
        sees that doctor fell through to AWS prereqs because of a load
        failure — silent fallback would mask config typos."""
        from lablink_cli.commands import doctor

        bad = tmp_path / "config.yaml"
        bad.write_text("provider: manual\n  bad indent: 1\n")  # malformed YAML
        monkeypatch.setattr(doctor, "DEFAULT_CONFIG", bad)

        cfg = doctor._load_config_safe()

        assert cfg is None
        out = capsys.readouterr().out
        assert "Could not load" in out
        assert "AWS prereq checks" in out


# ------------------------------------------------------------------
# run_doctor — manual provider dispatch
# ------------------------------------------------------------------
class TestDoctorManual:
    @patch("lablink_cli.commands.doctor.subprocess.run")
    @patch("lablink_cli.commands.doctor.shutil.which")
    @patch("lablink_cli.commands.doctor._load_config_safe")
    def test_manual_provider_checks_docker(
        self, mock_load, mock_which, mock_subproc, capsys,
    ):
        from lablink_cli.commands.doctor import run_doctor
        from lablink_cli.config.schema import Config

        cfg = Config()
        cfg.provider = "manual"
        mock_load.return_value = cfg
        mock_which.side_effect = lambda name: f"/usr/bin/{name}"
        mock_subproc.return_value = MagicMock(
            returncode=0,
            stdout="docker compose version 2.x",
            stderr="",
        )
        run_doctor()
        out = capsys.readouterr().out
        assert "docker" in out.lower()
