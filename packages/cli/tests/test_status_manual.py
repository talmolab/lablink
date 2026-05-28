"""Tests for lablink status on manual/BYO deployments."""

from __future__ import annotations

import io
import json
from unittest.mock import MagicMock, patch

import pytest
import yaml

from lablink_cli.commands.status import (
    _fetch_registered_clients,
    _render_manual_clients_table,
    _resolve_manual_admin_credentials,
    _run_status_manual,
)


# ---- _resolve_manual_admin_credentials ----------------------------------

class TestResolveManualAdminCredentials:
    def test_uses_cfg_when_present(self, tmp_path):
        cfg = MagicMock()
        cfg.app.admin_user = "admin"
        cfg.app.admin_password = "pw123"
        assert _resolve_manual_admin_credentials(cfg, tmp_path) == (
            "admin",
            "pw123",
        )

    def test_falls_back_to_workdir_config(self, tmp_path):
        cfg = MagicMock()
        cfg.app.admin_user = ""
        cfg.app.admin_password = ""
        (tmp_path / "config.yaml").write_text(
            yaml.safe_dump(
                {"app": {"admin_user": "op", "admin_password": "fromfile"}}
            )
        )
        assert _resolve_manual_admin_credentials(cfg, tmp_path) == (
            "op",
            "fromfile",
        )

    def test_ignores_missing_sentinel(self, tmp_path):
        cfg = MagicMock()
        cfg.app.admin_user = "MISSING"
        cfg.app.admin_password = "MISSING"
        assert _resolve_manual_admin_credentials(cfg, tmp_path) is None

    def test_returns_none_when_nothing_available(self, tmp_path):
        cfg = MagicMock()
        cfg.app.admin_user = ""
        cfg.app.admin_password = ""
        assert _resolve_manual_admin_credentials(cfg, tmp_path) is None


# ---- _fetch_registered_clients ------------------------------------------

class TestFetchRegisteredClients:
    @patch("lablink_cli.commands.status.urlopen")
    def test_sends_basic_auth_and_returns_clients(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = json.dumps(
            {"clients": [{"hostname": "byo-1"}]}
        ).encode()
        mock_urlopen.return_value = resp

        clients, err = _fetch_registered_clients(
            "http://localhost", "admin", "pw"
        )
        assert err == ""
        assert clients == [{"hostname": "byo-1"}]
        sent_req = mock_urlopen.call_args[0][0]
        # admin:pw → YWRtaW46cHc=
        assert sent_req.headers["Authorization"] == "Basic YWRtaW46cHc="
        assert sent_req.full_url == "http://localhost/api/v1/clients"

    @patch("lablink_cli.commands.status.urlopen")
    def test_returns_empty_list_when_response_missing_key(self, mock_urlopen):
        resp = MagicMock()
        resp.read.return_value = b"{}"
        mock_urlopen.return_value = resp
        clients, err = _fetch_registered_clients(
            "http://localhost", "admin", "pw"
        )
        assert clients == []
        assert err == ""

    @patch("lablink_cli.commands.status.urlopen")
    def test_returns_error_on_http_failure(self, mock_urlopen):
        from email.message import Message
        from urllib.error import HTTPError

        mock_urlopen.side_effect = HTTPError(
            "http://localhost/api/v1/clients",
            401,
            "Unauthorized",
            Message(),
            io.BytesIO(b""),
        )
        clients, err = _fetch_registered_clients(
            "http://localhost", "admin", "wrong"
        )
        assert clients is None
        assert "401" in err

    @patch("lablink_cli.commands.status.urlopen")
    def test_returns_error_on_url_failure(self, mock_urlopen):
        from urllib.error import URLError

        mock_urlopen.side_effect = URLError("connection refused")
        clients, err = _fetch_registered_clients(
            "http://localhost", "admin", "pw"
        )
        assert clients is None
        assert "connection refused" in err


# ---- _render_manual_clients_table ---------------------------------------

class TestRenderClientsTable:
    def test_runs_with_diverse_rows(self):
        # Smoke test: must not raise on the field shapes we expect from
        # the allocator (None values, mixed gpu_present, mixed healthy).
        _render_manual_clients_table(
            [
                {
                    "hostname": "byo-1",
                    "provider": "manual",
                    "status": "running",
                    "healthy": "true",
                    "inuse": False,
                    "gpu_present": True,
                    "gpu_model": "RTX 4090",
                    "endpoint_url": "ws://byo-1.local:6080",
                },
                {
                    "hostname": "byo-2",
                    "provider": "manual",
                    "status": "stopped",
                    "healthy": None,
                    "inuse": True,
                    "gpu_present": False,
                    "gpu_model": None,
                    "endpoint_url": None,
                },
                {
                    "hostname": "byo-3",
                    "provider": "manual",
                    "status": None,
                    "healthy": "false",
                    "inuse": None,
                    "gpu_present": None,
                    "gpu_model": None,
                    "endpoint_url": None,
                },
            ]
        )


# ---- _run_status_manual --------------------------------------------------

@pytest.fixture()
def manual_cfg():
    cfg = MagicMock()
    cfg.deployment_name = "mylab"
    cfg.ssl.provider = "none"
    cfg.app.admin_user = "admin"
    cfg.app.admin_password = "pw123"
    return cfg


def _make_workdir(tmp_path, deployment_name):
    """Build the workdir under tmp_path that _run_status_manual will look at."""
    workdir = tmp_path / ".lablink" / "compose" / deployment_name
    workdir.mkdir(parents=True)
    return workdir


class TestRunStatusManual:
    @patch("lablink_cli.commands.status.Path.home")
    def test_no_workdir(self, mock_home, manual_cfg, tmp_path):
        # tmp_path exists but does not contain a compose workdir for mylab.
        mock_home.return_value = tmp_path
        _run_status_manual(manual_cfg)  # must not raise

    @patch("lablink_cli.commands.status._fetch_registered_clients")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    @patch("lablink_cli.commands.status.subprocess.run")
    @patch("lablink_cli.commands.status.Path.home")
    def test_renders_clients_when_present(
        self,
        mock_home,
        mock_subproc,
        mock_health,
        mock_fetch,
        manual_cfg,
        tmp_path,
    ):
        mock_home.return_value = tmp_path
        _make_workdir(tmp_path, "mylab")
        mock_subproc.return_value = MagicMock(returncode=0, stdout="ps output")
        mock_health.return_value = {"healthy": True, "detail": "ok"}
        mock_fetch.return_value = (
            [
                {
                    "hostname": "byo-1",
                    "provider": "manual",
                    "status": "running",
                    "healthy": "true",
                    "inuse": False,
                    "gpu_present": True,
                    "gpu_model": "RTX 4090",
                    "endpoint_url": "ws://byo-1.local:6080",
                }
            ],
            "",
        )

        _run_status_manual(manual_cfg)

        mock_fetch.assert_called_once()
        assert mock_fetch.call_args[0] == ("http://localhost", "admin", "pw123")

    @patch("lablink_cli.commands.status._fetch_registered_clients")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    @patch("lablink_cli.commands.status.subprocess.run")
    @patch("lablink_cli.commands.status.Path.home")
    def test_handles_empty_client_list(
        self,
        mock_home,
        mock_subproc,
        mock_health,
        mock_fetch,
        manual_cfg,
        tmp_path,
        capsys,
    ):
        mock_home.return_value = tmp_path
        _make_workdir(tmp_path, "mylab")
        mock_subproc.return_value = MagicMock(returncode=0, stdout="")
        mock_health.return_value = {"healthy": True}
        mock_fetch.return_value = ([], "")
        _run_status_manual(manual_cfg)
        out = capsys.readouterr().out
        assert "No clients registered yet" in out

    @patch("lablink_cli.commands.status._fetch_registered_clients")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    @patch("lablink_cli.commands.status.subprocess.run")
    @patch("lablink_cli.commands.status.Path.home")
    def test_reports_fetch_failure(
        self,
        mock_home,
        mock_subproc,
        mock_health,
        mock_fetch,
        manual_cfg,
        tmp_path,
        capsys,
    ):
        mock_home.return_value = tmp_path
        _make_workdir(tmp_path, "mylab")
        mock_subproc.return_value = MagicMock(returncode=0, stdout="")
        mock_health.return_value = {"healthy": True}
        mock_fetch.return_value = (
            None,
            "HTTP 401 from http://localhost/api/v1/clients",
        )
        _run_status_manual(manual_cfg)
        out = capsys.readouterr().out
        assert "Failed to list clients" in out
        assert "401" in out

    @patch("lablink_cli.commands.status.check_health_endpoint")
    @patch("lablink_cli.commands.status.subprocess.run")
    @patch("lablink_cli.commands.status.Path.home")
    def test_warns_when_creds_missing(
        self,
        mock_home,
        mock_subproc,
        mock_health,
        manual_cfg,
        tmp_path,
        capsys,
    ):
        mock_home.return_value = tmp_path
        _make_workdir(tmp_path, "mylab")
        # Wipe creds out of cfg and leave no config.yaml in the workdir.
        manual_cfg.app.admin_user = ""
        manual_cfg.app.admin_password = ""
        mock_subproc.return_value = MagicMock(returncode=0, stdout="")
        mock_health.return_value = {"healthy": True}
        _run_status_manual(manual_cfg)
        out = capsys.readouterr().out
        assert "Admin credentials not found" in out
