"""Tests for lablink_cli.commands.doctor pre-flight checks."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch


from lablink_cli.commands.doctor import (
    _check_ami,
    _check_opentofu,
)
from lablink_cli.docker import Docker, DockerUnavailable, Result


# ------------------------------------------------------------------
# _check_opentofu
# ------------------------------------------------------------------
class TestCheckOpenTofu:
    @patch("shutil.which", return_value=None)
    def test_not_installed(self, _mock_which):
        result = _check_opentofu()
        assert result["status"] == "fail"
        assert "not found" in result["detail"]

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tofu")
    def test_looks_for_tofu_not_terraform(self, mock_which, mock_run):
        """The binary is `tofu`; a stray tofu on PATH must not satisfy it."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"terraform_version": "1.12.5"}),
        )

        _check_opentofu()
        mock_which.assert_called_once_with("tofu")
        assert mock_run.call_args[0][0] == ["tofu", "version", "-json"]

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tofu")
    def test_installed_with_version(self, _mock_which, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"terraform_version": "1.12.5"}),
        )

        result = _check_opentofu()
        assert result["status"] == "pass"
        assert "1.12.5" in result["detail"]

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tofu")
    def test_version_below_minimum_fails(self, _mock_which, mock_run):
        """Below 1.10.0 the S3 backend can corrupt state — refuse, don't warn."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"terraform_version": "1.6.6"}),
        )

        result = _check_opentofu()
        assert result["status"] == "fail"
        assert "1.10.0+" in result["detail"]
        assert "2485" in result["detail"]

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tofu")
    def test_opentofu_1_9_is_rejected(self, _mock_which, mock_run):
        """OpenTofu 1.9 vendors aws-sdk-go-v2 v1.23.2 — pre-fix, despite the
        version number matching the old OpenTofu floor."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"terraform_version": "1.9.1"}),
        )

        result = _check_opentofu()
        assert result["status"] == "fail"

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tofu")
    def test_two_component_minimum_passes(self, _mock_which, mock_run):
        """"1.10" means 1.10.0 and must clear the floor, not sort below it."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"terraform_version": "1.10"}),
        )

        result = _check_opentofu()
        assert result["status"] == "pass"

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tofu")
    def test_unparseable_version_passes(self, _mock_which, mock_run):
        """An unrecognised version string must not block the operator."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"terraform_version": "unknown"}),
        )

        result = _check_opentofu()
        assert result["status"] == "pass"

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tofu")
    def test_version_check_fails(self, _mock_which, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="")

        result = _check_opentofu()
        assert result["status"] == "warn"

    @patch("subprocess.run")
    @patch("shutil.which", return_value="/usr/bin/tofu")
    def test_timeout(self, _mock_which, mock_run):
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired("tofu", 10)

        result = _check_opentofu()
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
    @patch("lablink_cli.commands.doctor._load_config_safe")
    def test_manual_provider_checks_docker(self, mock_load, capsys):
        """run_doctor() with provider='manual' dispatches to
        _check_manual_prereqs(), which calls neither `doctor.shutil.which`
        nor `doctor.subprocess.run` — it goes through the Docker adapter
        (conftest's autouse fixture swaps in NullDocker). Assert on the
        lines NullDocker's "absent" answers actually produce, rather than
        patching two targets the code path never touches."""
        from lablink_cli.commands.doctor import run_doctor
        from lablink_cli.config.schema import Config

        cfg = Config()
        cfg.provider = "manual"
        mock_load.return_value = cfg

        run_doctor()

        out = capsys.readouterr().out
        assert "docker: not found" in out
        assert "docker compose: missing" in out


# ------------------------------------------------------------------
# _check_manual_prereqs
# ------------------------------------------------------------------
class _PrereqDocker(Docker):
    def __init__(self, *, path=None, compose_result=Result(0)):
        self._path = path
        self._compose_result = compose_result

    def path(self):
        return self._path

    def compose(self, workdir, *args, capture=True):
        if isinstance(self._compose_result, Exception):
            raise self._compose_result
        return self._compose_result


class TestCheckManualPrereqs:
    def test_docker_and_compose_available(self, capsys):
        from lablink_cli.commands.doctor import _check_manual_prereqs

        _check_manual_prereqs(
            docker=_PrereqDocker(path="/usr/bin/docker", compose_result=Result(0))
        )

        out = capsys.readouterr().out
        assert "docker: /usr/bin/docker" in out
        assert "docker compose: available" in out

    def test_docker_not_found(self, capsys):
        from lablink_cli.commands.doctor import _check_manual_prereqs

        _check_manual_prereqs(docker=_PrereqDocker(path=None))

        out = capsys.readouterr().out
        assert "docker: not found" in out

    def test_compose_missing_when_docker_vanishes_mid_check(self, capsys):
        """`compose` still calls `require()`, so a docker that disappears
        between the path check and the compose call surfaces as
        DockerUnavailable, not a crash."""
        from lablink_cli.commands.doctor import _check_manual_prereqs

        _check_manual_prereqs(
            docker=_PrereqDocker(
                path="/usr/bin/docker", compose_result=DockerUnavailable()
            )
        )

        out = capsys.readouterr().out
        assert "docker compose: missing" in out


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

        mock_docker = MagicMock()
        mock_docker.container_status.return_value = status
        return _check_client_container(mock_docker)

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
