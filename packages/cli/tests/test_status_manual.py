"""Tests for lablink status on manual/BYO deployments."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lablink_cli.commands.status import (
    _render_manual_clients_table,
    _run_status_manual,
)
from lablink_cli.docker import Docker, Result


class _ComposeDocker(Docker):
    """Answers `compose(workdir, "ps")` with a fixed Result."""

    def __init__(self, result=Result(0)):
        self._result = result

    def available(self):
        return True

    def require(self):
        return None

    def compose(self, workdir, *args, capture=True):
        return self._result


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


class TestRunStatusManual:
    def test_no_workdir(self, manual_cfg, tmp_path):
        # tmp_path exists but does not contain a compose workdir for mylab.
        _run_status_manual(manual_cfg, workdir_root=tmp_path)  # must not raise

    @patch("lablink_cli.manual.registered_clients")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    def test_renders_clients_when_present(
        self,
        mock_health,
        mock_fetch,
        manual_cfg,
        tmp_path,
    ):
        (tmp_path / "mylab").mkdir()
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

        _run_status_manual(
            manual_cfg,
            docker=_ComposeDocker(Result(0, stdout="ps output")),
            workdir_root=tmp_path,
        )

        mock_fetch.assert_called_once()
        assert mock_fetch.call_args[0] == (manual_cfg, "admin", "pw123")

    @patch("lablink_cli.manual.registered_clients")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    def test_handles_empty_client_list(
        self,
        mock_health,
        mock_fetch,
        manual_cfg,
        tmp_path,
        capsys,
    ):
        (tmp_path / "mylab").mkdir()
        mock_health.return_value = {"healthy": True}
        mock_fetch.return_value = ([], "")
        _run_status_manual(
            manual_cfg, docker=_ComposeDocker(), workdir_root=tmp_path
        )
        out = capsys.readouterr().out
        assert "No clients registered yet" in out

    @patch("lablink_cli.manual.registered_clients")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    def test_reports_fetch_failure(
        self,
        mock_health,
        mock_fetch,
        manual_cfg,
        tmp_path,
        capsys,
    ):
        (tmp_path / "mylab").mkdir()
        mock_health.return_value = {"healthy": True}
        mock_fetch.return_value = (
            None,
            "HTTP 401 from http://localhost:80/api/v1/clients",
        )
        _run_status_manual(
            manual_cfg, docker=_ComposeDocker(), workdir_root=tmp_path
        )
        out = capsys.readouterr().out
        assert "Failed to list clients" in out
        assert "401" in out

    @patch("lablink_cli.commands.status.check_health_endpoint")
    def test_warns_when_creds_missing(
        self,
        mock_health,
        manual_cfg,
        tmp_path,
        capsys,
    ):
        (tmp_path / "mylab").mkdir()
        # Wipe creds out of cfg and leave no config.yaml in the workdir.
        manual_cfg.app.admin_user = ""
        manual_cfg.app.admin_password = ""
        mock_health.return_value = {"healthy": True}
        _run_status_manual(
            manual_cfg, docker=_ComposeDocker(), workdir_root=tmp_path
        )
        out = capsys.readouterr().out
        assert "Admin credentials not found" in out

    @patch("lablink_cli.commands.status.check_health_endpoint")
    def test_health_probe_hits_canonical_localhost_port(
        self, mock_health, manual_cfg, tmp_path
    ):
        # Regression: this probe used to build "https://localhost" (no
        # port, unreachable-for-manual https branch) instead of the same
        # base URL every other manual path uses.
        (tmp_path / "mylab").mkdir()
        manual_cfg.app.admin_user = ""
        manual_cfg.app.admin_password = ""
        manual_cfg.ssl.provider = "self_signed"
        mock_health.return_value = {"healthy": True}
        _run_status_manual(
            manual_cfg, docker=_ComposeDocker(), workdir_root=tmp_path
        )
        assert mock_health.call_args_list[0][0][0] == "http://localhost:80"

    @patch("lablink_cli.manual.registered_clients")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    def test_external_runtime_skips_compose_ps_and_uses_canonical_url(
        self, mock_health, mock_clients, manual_cfg, tmp_path
    ):
        from lablink_cli.manual import RUNTIME_FILENAME

        workdir = tmp_path / "mylab"
        workdir.mkdir()
        (workdir / RUNTIME_FILENAME).write_text("external\n")
        (workdir / "allocator-url").write_text("https://lab.example.org")
        manual_cfg.manual.participant_exposure = "cloudflare_tunnel"
        mock_health.return_value = {"healthy": True}
        mock_clients.return_value = ([], "")

        fake_docker = MagicMock()
        _run_status_manual(
            manual_cfg, docker=fake_docker, workdir_root=tmp_path
        )

        fake_docker.compose.assert_not_called()
        # Both HTTP checks target the canonical public URL, not localhost.
        assert (
            mock_health.call_args_list[0][0][0] == "https://lab.example.org"
        )
        assert (
            mock_clients.call_args.kwargs["base"] == "https://lab.example.org"
        )

    @patch("lablink_cli.manual.registered_clients")
    @patch("lablink_cli.commands.status.check_health_endpoint")
    def test_external_runtime_missing_url_reports_explicitly(
        self, mock_health, mock_clients, manual_cfg, tmp_path, capsys
    ):
        """A render-only bundle with no supported public exposure has no
        address to probe — say so, instead of silently falling back to a
        localhost that has nothing listening on it."""
        from lablink_cli.manual import RUNTIME_FILENAME

        workdir = tmp_path / "mylab"
        workdir.mkdir()
        (workdir / RUNTIME_FILENAME).write_text("external\n")
        # No allocator-url file recorded.

        fake_docker = MagicMock()
        _run_status_manual(
            manual_cfg, docker=fake_docker, workdir_root=tmp_path
        )

        out = capsys.readouterr().out
        assert "No public URL recorded" in out
        mock_health.assert_not_called()
        mock_clients.assert_not_called()
