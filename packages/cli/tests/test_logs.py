"""Tests for lablink_cli.commands.logs SSH helpers."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from lablink_cli.commands.logs import (
    _ssh_via_instance_connect,
    _ssh_via_private_key,
)


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
    @patch("lablink_cli.commands.logs.get_terraform_outputs")
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

    @patch("lablink_cli.commands.logs.get_terraform_outputs")
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
    @patch("lablink_cli.commands.logs.get_terraform_outputs")
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
    @patch("lablink_cli.commands.logs.get_terraform_outputs")
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
class TestFetchManualAllocatorLogs:
    @patch("lablink_cli.commands.logs.subprocess.run")
    def test_success_returns_docker_logs(self, mock_run):
        from lablink_cli.commands.logs import fetch_manual_allocator_logs

        mock_run.return_value = MagicMock(
            returncode=0, stdout="line 1\nline 2\n", stderr=""
        )

        result = fetch_manual_allocator_logs()

        assert result["error"] is None
        assert result["cloud_init_logs"] is None
        assert result["docker_logs"] == "line 1\nline 2"
        # Calls `docker logs --tail N lablink-allocator`.
        cmd = mock_run.call_args.args[0]
        assert cmd[:2] == ["docker", "logs"]
        assert "--tail" in cmd
        assert "lablink-allocator" in cmd

    @patch("lablink_cli.commands.logs.subprocess.run")
    def test_no_such_container_returns_friendly_error(self, mock_run):
        from lablink_cli.commands.logs import fetch_manual_allocator_logs

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: No such container: lablink-allocator\n",
        )

        result = fetch_manual_allocator_logs()

        assert result["docker_logs"] is None
        assert "lablink-allocator container is not running" in result["error"]

    @patch("lablink_cli.commands.logs.subprocess.run")
    def test_other_nonzero_returns_stderr(self, mock_run):
        from lablink_cli.commands.logs import fetch_manual_allocator_logs

        mock_run.return_value = MagicMock(
            returncode=2, stdout="", stderr="permission denied\n"
        )

        result = fetch_manual_allocator_logs()

        assert result["docker_logs"] is None
        assert "permission denied" in result["error"]

    @patch("lablink_cli.commands.logs.subprocess.run")
    def test_docker_missing_returns_error(self, mock_run):
        from lablink_cli.commands.logs import fetch_manual_allocator_logs

        mock_run.side_effect = FileNotFoundError("docker")

        result = fetch_manual_allocator_logs()

        assert result["docker_logs"] is None
        assert "docker logs failed" in result["error"]

    @patch("lablink_cli.commands.logs.subprocess.run")
    def test_merges_stdout_and_stderr(self, mock_run):
        """Container can write to both stdout and stderr; the TUI shows one
        chronological view."""
        from lablink_cli.commands.logs import fetch_manual_allocator_logs

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="[info] up\n",
            stderr="[warn] slow query\n",
        )

        result = fetch_manual_allocator_logs()

        assert "up" in result["docker_logs"]
        assert "slow query" in result["docker_logs"]


# ------------------------------------------------------------------
# Manual-provider TUI launcher (_run_logs_manual)
# ------------------------------------------------------------------
class TestRunLogsManualTui:
    def _patch_common(self):
        """Patches shared by every test in this class."""
        return [
            patch("lablink_cli.commands.status._resolve_manual_admin_credentials"),
            patch("lablink_cli.commands.status._fetch_registered_clients"),
            patch("lablink_cli.tui.logs_viewer.LogsApp"),
        ]

    def test_launches_tui_with_allocator_and_clients(self, mock_cfg):
        from lablink_cli.commands.logs import run_logs

        mock_cfg.provider = "manual"
        mock_cfg.deployment_name = "testlab"

        with patch(
            "lablink_cli.commands.status._resolve_manual_admin_credentials",
            return_value=("admin", "pw"),
        ), patch(
            "lablink_cli.commands.status._fetch_registered_clients",
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
            "lablink_cli.commands.status._resolve_manual_admin_credentials",
            return_value=("admin", "pw"),
        ), patch(
            "lablink_cli.commands.status._fetch_registered_clients",
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
            "lablink_cli.commands.status._resolve_manual_admin_credentials",
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
            "lablink_cli.commands.status._resolve_manual_admin_credentials",
            return_value=("admin", "pw"),
        ), patch(
            "lablink_cli.commands.status._fetch_registered_clients",
            return_value=(None, "connection refused"),
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
            "lablink_cli.commands.status._resolve_manual_admin_credentials",
            return_value=("admin", "pw"),
        ), patch(
            "lablink_cli.commands.status._fetch_registered_clients",
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
