"""Tests for lablink_cli.commands.logs SSH helpers."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

from lablink_cli.commands.logs import (
    _ssh_via_instance_connect,
    _ssh_via_private_key,
    fetch_manual_allocator_logs,
)
from lablink_cli.docker import Docker, Result


class TestSshViaInstanceConnect:
    @patch("lablink_cli.commands.logs.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="log output"
        )
        result = _ssh_via_instance_connect(
            "i-123", "us-east-1", "echo hello"
        )
        assert result == "log output"
        mock_run.assert_called_once()

    @patch("lablink_cli.commands.logs.subprocess.run")
    def test_nonzero_exit_returns_none(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="error"
        )
        result = _ssh_via_instance_connect(
            "i-123", "us-east-1", "echo hello"
        )
        assert result is None

    @patch("lablink_cli.commands.logs.subprocess.run")
    def test_timeout_returns_none(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="ssh", timeout=30
        )
        result = _ssh_via_instance_connect(
            "i-123", "us-east-1", "echo hello"
        )
        assert result is None

    @patch("lablink_cli.commands.logs.subprocess.run")
    def test_file_not_found_returns_none(self, mock_run):
        mock_run.side_effect = FileNotFoundError("aws not found")
        result = _ssh_via_instance_connect(
            "i-123", "us-east-1", "echo hello"
        )
        assert result is None


class TestSshViaPrivateKey:
    @patch("lablink_cli.commands.logs.subprocess.run")
    @patch("lablink_cli.commands.logs.get_tofu_outputs")
    def test_success(self, mock_outputs, mock_run, tmp_path):
        mock_outputs.return_value = {
            "private_key_pem": "-----BEGIN RSA PRIVATE KEY-----\n"
            "fake\n"
            "-----END RSA PRIVATE KEY-----"
        }
        mock_run.return_value = MagicMock(
            returncode=0, stdout="log output"
        )
        result = _ssh_via_private_key(
            "1.2.3.4", "echo hello", tmp_path
        )
        assert result == "log output"

    @patch("lablink_cli.commands.logs.get_tofu_outputs")
    def test_no_private_key_returns_none(self, mock_outputs, tmp_path):
        mock_outputs.return_value = {}
        result = _ssh_via_private_key(
            "1.2.3.4", "echo hello", tmp_path
        )
        assert result is None

    def test_no_ip_returns_none(self, tmp_path):
        result = _ssh_via_private_key(
            "\u2014", "echo hello", tmp_path
        )
        assert result is None

    @patch("lablink_cli.commands.logs.subprocess.run")
    @patch("lablink_cli.commands.logs.get_tofu_outputs")
    def test_nonzero_exit_returns_stderr(self, mock_outputs, mock_run, tmp_path):
        mock_outputs.return_value = {
            "private_key_pem": "-----BEGIN RSA PRIVATE KEY-----\n"
            "fake\n"
            "-----END RSA PRIVATE KEY-----"
        }
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="connection refused"
        )
        result = _ssh_via_private_key(
            "1.2.3.4", "echo hello", tmp_path
        )
        assert "connection refused" in result

    @patch("lablink_cli.commands.logs.subprocess.run")
    @patch("lablink_cli.commands.logs.get_tofu_outputs")
    def test_timeout_returns_none(self, mock_outputs, mock_run, tmp_path):
        mock_outputs.return_value = {
            "private_key_pem": "-----BEGIN RSA PRIVATE KEY-----\n"
            "fake\n"
            "-----END RSA PRIVATE KEY-----"
        }
        mock_run.side_effect = subprocess.TimeoutExpired(
            cmd="ssh", timeout=30
        )
        result = _ssh_via_private_key(
            "1.2.3.4", "echo hello", tmp_path
        )
        assert result is None


# ------------------------------------------------------------------
# fetch_manual_allocator_logs — local docker container
# ------------------------------------------------------------------
class LogsDocker(Docker):
    def __init__(self, result):
        self._result = result

    def available(self):
        return True

    def require(self):
        return None

    def logs(self, name, *, tail=None, merge_stderr=False, timeout=None):
        return self._result


def test_manual_allocator_logs_returns_output():
    out = fetch_manual_allocator_logs(docker=LogsDocker(Result(0, stdout="hi")))
    assert out["docker_logs"] == "hi"
    assert out["error"] is None


def test_manual_allocator_logs_explains_missing_container():
    fake = LogsDocker(Result(1, stderr="Error: No such container: x"))
    out = fetch_manual_allocator_logs(docker=fake)
    assert "not running" in out["error"]


class TestFetchManualAllocatorLogs:
    def test_success_returns_docker_logs(self):
        result = fetch_manual_allocator_logs(
            docker=LogsDocker(Result(0, stdout="line 1\nline 2\n"))
        )

        assert result["error"] is None
        assert result["cloud_init_logs"] is None
        assert result["docker_logs"] == "line 1\nline 2"

    def test_no_such_container_returns_friendly_error(self):
        result = fetch_manual_allocator_logs(
            docker=LogsDocker(
                Result(1, stderr="Error: No such container: lablink-allocator\n")
            )
        )

        assert result["docker_logs"] is None
        assert "lablink-allocator container is not running" in result["error"]

    def test_other_nonzero_returns_stderr(self):
        result = fetch_manual_allocator_logs(
            docker=LogsDocker(Result(2, stderr="permission denied\n"))
        )

        assert result["docker_logs"] is None
        assert "permission denied" in result["error"]

    def test_merges_stdout_and_stderr(self):
        """Container can write to both stdout and stderr; the TUI shows one
        chronological view."""
        result = fetch_manual_allocator_logs(
            docker=LogsDocker(
                Result(0, stdout="[info] up\n", stderr="[warn] slow query\n")
            )
        )

        assert "up" in result["docker_logs"]
        assert "slow query" in result["docker_logs"]

    def test_docker_missing_from_path_does_not_raise(self):
        """End-to-end with the real adapter (not the LogsDocker fake): a
        docker binary genuinely absent from PATH must come back as a
        friendly error dict, not an uncaught DockerUnavailable — the only
        caller, the TUI's logs viewer, has no try/except around this call."""
        with patch("lablink_cli.docker.shutil.which", return_value=None), patch(
            "lablink_cli.docker.subprocess.run",
            side_effect=FileNotFoundError("docker"),
        ):
            result = fetch_manual_allocator_logs(docker=Docker())

        assert result["docker_logs"] is None
        assert result["error"]


# ------------------------------------------------------------------
# fetch_external_allocator_logs — external-runtime allocator (HTTP)
# ------------------------------------------------------------------
class TestFetchExternalAllocatorLogs:
    @patch("lablink_cli.commands.logs.authenticated_json_request")
    def test_fetches_via_authenticated_json_request(self, mock_fetch):
        """Routed through the CLI's own HTTP layer (product User-Agent),
        not a bare `requests.get` — Cloudflare-proxied allocators (this
        feature's own topology) 403 the default UA."""
        from lablink_cli.commands.logs import fetch_external_allocator_logs

        mock_fetch.return_value = {
            "cloud_init_logs": None,
            "docker_logs": "line1\nline2",
            "error": None,
        }
        out = fetch_external_allocator_logs(
            allocator_url="https://lab.example.org",
            admin_user="admin",
            admin_password="pw",
            ssl_provider="none",
        )
        assert out["docker_logs"] == "line1\nline2"
        args, kwargs = mock_fetch.call_args
        assert args[0] == "https://lab.example.org/api/allocator-logs"
        assert args[1] == "admin"
        assert args[2] == "pw"
        assert kwargs["ssl_provider"] == "none"

    @patch("lablink_cli.commands.logs.authenticated_json_request")
    def test_http_failure_reports_error_in_contract_shape(self, mock_fetch):
        from lablink_cli.commands.logs import fetch_external_allocator_logs

        mock_fetch.side_effect = URLError("boom")
        out = fetch_external_allocator_logs(
            allocator_url="https://lab.example.org",
            admin_user="admin",
            admin_password="pw",
        )
        assert out["docker_logs"] is None
        assert "is the platform workload running" in out["error"]

    @patch("lablink_cli.commands.logs.authenticated_json_request")
    def test_http_error_reports_error_in_contract_shape(self, mock_fetch):
        import io
        from email.message import Message

        from lablink_cli.commands.logs import fetch_external_allocator_logs

        mock_fetch.side_effect = HTTPError(
            "https://lab.example.org/api/allocator-logs",
            403,
            "Forbidden",
            Message(),
            io.BytesIO(b""),
        )
        out = fetch_external_allocator_logs(
            allocator_url="https://lab.example.org",
            admin_user="admin",
            admin_password="pw",
        )
        assert out["docker_logs"] is None
        assert "is the platform workload running" in out["error"]

    @patch("lablink_cli.commands.logs.authenticated_json_request")
    def test_malformed_json_reports_error_in_contract_shape(self, mock_fetch):
        from lablink_cli.commands.logs import fetch_external_allocator_logs

        mock_fetch.side_effect = json.JSONDecodeError("bad", "doc", 0)
        out = fetch_external_allocator_logs(
            allocator_url="https://lab.example.org",
            admin_user="admin",
            admin_password="pw",
        )
        assert out["docker_logs"] is None
        assert "is the platform workload running" in out["error"]


# ------------------------------------------------------------------
# Manual-provider TUI launcher (_run_logs_manual)
# ------------------------------------------------------------------
class TestRunLogsManualTui:
    def _patch_common(self):
        """Patches shared by every test in this class."""
        return [
            patch("lablink_cli.manual.admin_credentials"),
            patch("lablink_cli.manual.registered_clients"),
            patch("lablink_cli.tui.logs_viewer.LogsApp"),
        ]

    def test_launches_tui_with_allocator_and_clients(self, mock_cfg):
        from lablink_cli.commands.logs import run_logs

        mock_cfg.provider = "manual"
        mock_cfg.deployment_name = "testlab"

        with patch(
            "lablink_cli.manual.admin_credentials",
            return_value=("admin", "pw"),
        ), patch(
            "lablink_cli.manual.registered_clients",
            return_value=([
                {"hostname": "byo-01", "lan_ip": "192.168.1.10"},
                {"hostname": "byo-02", "lan_ip": "192.168.1.11"},
            ], ""),
        ), patch(
            "lablink_cli.tui.logs_viewer.LogsApp"
        ) as mock_app_cls:
            mock_app_cls.return_value = MagicMock()

            run_logs(mock_cfg)

        # LogsApp invoked with manual=True and a VM list containing
        # allocator + both clients.
        kwargs = mock_app_cls.call_args.kwargs
        assert kwargs["manual"] is True
        names = [vm["name"] for vm in kwargs["vms"]]
        assert names[0] == "lablink-allocator"
        assert "byo-01" in names
        assert "byo-02" in names
        # Allocator gets vm_type="allocator"; clients get vm_type="client".
        types = {vm["name"]: vm["vm_type"] for vm in kwargs["vms"]}
        assert types["lablink-allocator"] == "allocator"
        assert types["byo-01"] == "client"
        # Every VM dict must carry the keys VMListItem reads: vm_type, name,
        # state. Missing state crashes the TUI at compose time.
        required_keys = {"vm_type", "name", "state", "type", "public_ip"}
        for vm in kwargs["vms"]:
            assert required_keys.issubset(vm.keys()), (
                f"VM dict missing keys: {required_keys - vm.keys()}"
            )

    def test_no_clients_still_shows_allocator(self, mock_cfg):
        from lablink_cli.commands.logs import run_logs

        mock_cfg.provider = "manual"
        mock_cfg.deployment_name = "testlab"

        with patch(
            "lablink_cli.manual.admin_credentials",
            return_value=("admin", "pw"),
        ), patch(
            "lablink_cli.manual.registered_clients",
            return_value=([], ""),
        ), patch(
            "lablink_cli.tui.logs_viewer.LogsApp"
        ) as mock_app_cls:
            mock_app_cls.return_value = MagicMock()

            run_logs(mock_cfg)

        vms = mock_app_cls.call_args.kwargs["vms"]
        assert len(vms) == 1
        assert vms[0]["name"] == "lablink-allocator"

    def test_missing_creds_exits_with_helpful_message(self, mock_cfg):
        import pytest
        from lablink_cli.commands.logs import run_logs

        mock_cfg.provider = "manual"
        mock_cfg.deployment_name = "testlab"

        with patch(
            "lablink_cli.manual.admin_credentials",
            return_value=None,
        ):
            with pytest.raises(SystemExit) as exc:
                run_logs(mock_cfg)

        assert exc.value.code == 1

    def test_fetch_clients_failure_exits(self, mock_cfg):
        import pytest
        from lablink_cli.commands.logs import run_logs

        mock_cfg.provider = "manual"
        mock_cfg.deployment_name = "testlab"

        with patch(
            "lablink_cli.manual.admin_credentials",
            return_value=("admin", "pw"),
        ), patch(
            "lablink_cli.manual.registered_clients",
            return_value=(None, "connection refused"),
        ):
            with pytest.raises(SystemExit) as exc:
                run_logs(mock_cfg)

        assert exc.value.code == 1

    def test_external_runtime_uses_public_url_and_external_fetcher(self, mock_cfg):
        """An external-runtime deployment has no localhost port to probe —
        the allocator URL and log fetcher must come from its public URL."""
        from lablink_cli.commands.logs import run_logs

        mock_cfg.provider = "manual"
        mock_cfg.deployment_name = "testlab"

        with patch(
            "lablink_cli.manual.admin_credentials",
            return_value=("admin", "pw"),
        ), patch(
            "lablink_cli.manual.deployment_runtime",
            return_value="external",
        ), patch(
            "lablink_cli.manual.public_url",
            return_value="https://lab.example.org",
        ), patch(
            "lablink_cli.manual.registered_clients",
            return_value=([], ""),
        ) as mock_fetch_clients, patch(
            "lablink_cli.tui.logs_viewer.LogsApp"
        ) as mock_app_cls:
            mock_app_cls.return_value = MagicMock()

            run_logs(mock_cfg)

        # Clients discovered against the public URL, not localhost.
        assert (
            mock_fetch_clients.call_args.kwargs["base"]
            == "https://lab.example.org"
        )
        kwargs = mock_app_cls.call_args.kwargs
        assert kwargs["allocator_url"] == "https://lab.example.org"
        assert kwargs["runtime"] == "external"

    def test_external_runtime_missing_public_url_exits(self, mock_cfg):
        import pytest
        from lablink_cli.commands.logs import run_logs

        mock_cfg.provider = "manual"
        mock_cfg.deployment_name = "testlab"

        with patch(
            "lablink_cli.manual.admin_credentials",
            return_value=("admin", "pw"),
        ), patch(
            "lablink_cli.manual.deployment_runtime",
            return_value="external",
        ), patch(
            "lablink_cli.manual.public_url",
            return_value=None,
        ):
            with pytest.raises(SystemExit) as exc:
                run_logs(mock_cfg)

        assert exc.value.code == 1

    def test_does_not_touch_aws_paths(self, mock_cfg):
        """Manual provider must not call list_all_vms, get_deploy_dir, etc."""
        from lablink_cli.commands.logs import run_logs

        mock_cfg.provider = "manual"
        mock_cfg.deployment_name = "testlab"

        with patch(
            "lablink_cli.manual.admin_credentials",
            return_value=("admin", "pw"),
        ), patch(
            "lablink_cli.manual.registered_clients",
            return_value=([], ""),
        ), patch(
            "lablink_cli.tui.logs_viewer.LogsApp"
        ), patch(
            "lablink_cli.commands.logs.get_deploy_dir"
        ) as mock_deploy_dir, patch(
            "lablink_cli.commands.logs.list_all_vms"
        ) as mock_list_vms:
            run_logs(mock_cfg)

        mock_deploy_dir.assert_not_called()
        mock_list_vms.assert_not_called()


class TestRunLogsAwsQueryFailure:
    def test_credential_failure_exits_cleanly(self, mock_cfg, tmp_path, capsys):
        """list_all_vms now raises instead of returning [] — run_logs must
        report it, not traceback."""
        import pytest

        from lablink_cli.commands.logs import run_logs
        from lablink_cli.commands.utils import AwsQueryError

        deploy_dir = tmp_path / "deploy"
        deploy_dir.mkdir()

        with patch(
            "lablink_cli.commands.logs.get_deploy_dir",
            return_value=deploy_dir,
        ), patch(
            "lablink_cli.commands.logs.list_all_vms",
            side_effect=AwsQueryError(
                "AWS credentials are expired (ExpiredToken)", is_auth=True
            ),
        ):
            with pytest.raises(SystemExit) as exc:
                run_logs(mock_cfg)

        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "ExpiredToken" in out
        assert "aws configure" in out
        assert "No running VMs found" not in out
