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
            stdout=json.dumps({"terraform_version": "1.9.8"}),
        )

        result = _check_terraform()
        assert result["status"] == "pass"
        assert "1.9.8" in result["detail"]

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/terraform")
    def test_version_below_minimum_fails(self, _mock_which, mock_run):
        """Below 1.9.0 the S3 backend can corrupt state — refuse, don't warn."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"terraform_version": "1.6.6"}),
        )

        result = _check_terraform()
        assert result["status"] == "fail"
        assert "1.9.0+" in result["detail"]
        assert "34528" in result["detail"]

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/terraform")
    def test_newer_major_minor_passes(self, _mock_which, mock_run):
        """A two-component version must not crash the tuple comparison."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"terraform_version": "1.10"}),
        )

        result = _check_terraform()
        assert result["status"] == "pass"

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/terraform")
    def test_unparseable_version_passes(self, _mock_which, mock_run):
        """An unrecognised version string must not block the operator."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"terraform_version": "unknown"}),
        )

        result = _check_terraform()
        assert result["status"] == "pass"

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


# ------------------------------------------------------------------
# Client-side checks (`lablink client doctor`)
# ------------------------------------------------------------------
class TestCheckClientRegistered:
    def test_missing_env_file(self, tmp_path):
        from lablink_cli.commands.doctor import _check_client_registered

        with patch(
            "lablink_cli.commands.register.DEFAULT_ENV_FILE",
            tmp_path / "nope.env",
        ):
            result = _check_client_registered()

        assert result["status"] == "fail"
        assert "lablink client register" in result["detail"]

    def test_env_file_present(self, tmp_path):
        from lablink_cli.commands.doctor import _check_client_registered

        env_file = tmp_path / "client.env"
        env_file.write_text("VM_NAME=box\n")
        with patch(
            "lablink_cli.commands.register.DEFAULT_ENV_FILE", env_file
        ):
            result = _check_client_registered()

        assert result["status"] == "pass"


class TestCheckClientContainer:
    def _run(self, status):
        from lablink_cli.commands.doctor import _check_client_container

        with patch(
            "lablink_cli.log_shipper.inspect_container", return_value=status
        ):
            return _check_client_container()

    def test_running_passes(self):
        assert self._run("running")["status"] == "pass"

    def test_restarting_warns_about_crash_loop(self):
        result = self._run("restarting")
        assert result["status"] == "warn"
        assert "crash-looping" in result["detail"]

    def test_missing_suggests_force(self):
        result = self._run("missing")
        assert result["status"] == "fail"
        assert "--force" in result["detail"]

    def test_exited_fails(self):
        assert self._run("exited")["status"] == "fail"

    def test_daemon_error_reported_as_daemon_problem(self):
        result = self._run("daemon_error")
        assert result["status"] == "fail"
        assert "daemon" in result["detail"].lower()


class TestCheckLogShipper:
    # 2026-08-05T12:00:00Z
    SHIPPED = "2026-08-05T12:00:00Z"
    SHIPPED_EPOCH = 1785931200.0

    def _run(self, *, alive, last, now=None):
        from lablink_cli.commands.doctor import _check_log_shipper

        with (
            patch(
                "lablink_cli.commands.register._shipper_alive",
                return_value=alive,
            ),
            patch(
                "lablink_cli.log_shipper.read_last_shipped_ts",
                return_value=last,
            ),
        ):
            return _check_log_shipper(now=now)

    def test_dead_shipper_fails(self):
        result = self._run(alive=False, last=self.SHIPPED)
        assert result["status"] == "fail"
        assert "not reaching the allocator" in result["detail"].lower()

    def test_alive_and_recent_passes(self):
        result = self._run(
            alive=True, last=self.SHIPPED, now=self.SHIPPED_EPOCH + 60
        )
        assert result["status"] == "pass"

    def test_alive_but_stale_warns(self):
        """The failure a liveness-only check cannot see: process up,
        container healthy, nothing reaching the allocator."""
        result = self._run(
            alive=True, last=self.SHIPPED, now=self.SHIPPED_EPOCH + 6 * 86400
        )
        assert result["status"] == "warn"
        assert "6d ago" in result["detail"]
        assert self.SHIPPED in result["detail"]

    def test_age_formatting_stays_readable(self):
        from lablink_cli.commands.doctor import _format_age

        assert _format_age(20 * 60) == "20m"
        assert _format_age(3 * 3600) == "3h"
        assert _format_age(6 * 86400) == "6d"

    def test_alive_but_never_shipped_warns(self):
        result = self._run(alive=True, last=None)
        assert result["status"] == "warn"
        assert "never shipped" in result["detail"]

    def test_unparseable_timestamp_warns(self):
        result = self._run(alive=True, last="not-a-timestamp")
        assert result["status"] == "warn"


class TestRunClientDoctor:
    def test_renders_all_three_checks(self, capsys):
        from lablink_cli.commands.doctor import run_client_doctor

        with (
            patch(
                "lablink_cli.commands.doctor._check_client_registered",
                return_value={"check": "Registered", "status": "pass"},
            ),
            patch(
                "lablink_cli.commands.doctor._check_client_container",
                return_value={"check": "Client container", "status": "pass"},
            ),
            patch(
                "lablink_cli.commands.doctor._check_log_shipper",
                return_value={"check": "Log shipper", "status": "pass"},
            ),
        ):
            run_client_doctor()

        out = capsys.readouterr().out
        assert "Registered" in out
        assert "Log shipper" in out
        assert "All checks passed" in out
