"""Tests for lablink_cli.commands.launch client VM launching."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lablink_cli.api import (
    AllocatorAuthError,
    AllocatorError,
    AllocatorNotFoundError,
    AllocatorUnavailableError,
)
from lablink_cli.commands.launch import run_client_destroy, run_launch


class TestRunLaunch:
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_no_allocator_url(self, mock_url, mock_creds, mock_cfg):
        mock_url.return_value = ""

        with pytest.raises(SystemExit):
            run_launch(mock_cfg, num_vms=1)

    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_successful_launch(
        self, mock_url, mock_creds, mock_api_cls, mock_cfg
    ):
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_api = MagicMock()
        mock_api.launch_vms.return_value = {
            "status": "success", "output": "Created 2 VMs",
        }
        mock_api_cls.return_value = mock_api

        # Should not raise
        run_launch(mock_cfg, num_vms=2)

        mock_api_cls.assert_called_once_with(
            "http://1.2.3.4", "admin", "password", mock_cfg.ssl.provider
        )
        mock_api.launch_vms.assert_called_once()
        assert mock_api.launch_vms.call_args.args == (2,)
        assert callable(mock_api.launch_vms.call_args.kwargs["on_progress"])

    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_auth_failure(self, mock_url, mock_creds, mock_api_cls, mock_cfg):
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "wrong")
        mock_api = MagicMock()
        mock_api.launch_vms.side_effect = AllocatorAuthError(
            "Authentication failed"
        )
        mock_api_cls.return_value = mock_api

        with pytest.raises(SystemExit):
            run_launch(mock_cfg, num_vms=1)

    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_connection_error(
        self, mock_url, mock_creds, mock_api_cls, mock_cfg
    ):
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_api = MagicMock()
        mock_api.launch_vms.side_effect = AllocatorUnavailableError(
            "connection refused"
        )
        mock_api_cls.return_value = mock_api

        with pytest.raises(SystemExit):
            run_launch(mock_cfg, num_vms=1)

    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_self_signed_ssl(
        self, mock_url, mock_creds, mock_api_cls, mock_cfg
    ):
        mock_url.return_value = "https://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_cfg.ssl.provider = "self_signed"
        mock_api = MagicMock()
        mock_api.launch_vms.return_value = {"status": "success", "output": ""}
        mock_api_cls.return_value = mock_api

        run_launch(mock_cfg, num_vms=1)

        mock_api_cls.assert_called_once_with(
            "https://1.2.3.4", "admin", "password", "self_signed"
        )

    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_http_server_error(
        self, mock_url, mock_creds, mock_api_cls, mock_cfg
    ):
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_api = MagicMock()
        mock_api.launch_vms.side_effect = AllocatorError(
            "HTTP 500: out of capacity"
        )
        mock_api_cls.return_value = mock_api

        with pytest.raises(SystemExit):
            run_launch(mock_cfg, num_vms=1)


    @patch("lablink_cli.commands.launch.Progress")
    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_progress_bar_updates_from_on_progress_callback(
        self, mock_url, mock_creds, mock_api_cls, mock_progress_cls, mock_cfg,
    ):
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")

        mock_progress = MagicMock()
        mock_progress.add_task.return_value = "task-id"
        mock_progress_cls.return_value.__enter__.return_value = mock_progress

        captured = {}

        def fake_launch_vms(num_vms, on_progress=None):
            captured["on_progress"] = on_progress
            return {"status": "success", "output": ""}

        mock_api = MagicMock()
        mock_api.launch_vms.side_effect = fake_launch_vms
        mock_api_cls.return_value = mock_api

        run_launch(mock_cfg, num_vms=2)

        captured["on_progress"](3, 5)
        mock_progress.update.assert_called_with(
            "task-id",
            completed=3,
            total=5,
            description=(
                "[bold]Launching 2 client VM(s)...[/bold] (3/5 resources)"
            ),
        )

    @patch("lablink_cli.commands.launch.Progress")
    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_progress_bar_not_updated_when_total_unknown(
        self, mock_url, mock_creds, mock_api_cls, mock_progress_cls, mock_cfg,
    ):
        """Polling an allocator that predates progress reporting sends
        (None, None) — the progress bar must stay in its indeterminate
        state, not attempt an update with a None total."""
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_progress = MagicMock()
        mock_progress.add_task.return_value = "task-id"
        mock_progress_cls.return_value.__enter__.return_value = mock_progress

        captured = {}

        def fake_launch_vms(num_vms, on_progress=None):
            captured["on_progress"] = on_progress
            return {"status": "success", "output": ""}

        mock_api = MagicMock()
        mock_api.launch_vms.side_effect = fake_launch_vms
        mock_api_cls.return_value = mock_api

        run_launch(mock_cfg, num_vms=1)

        captured["on_progress"](None, None)
        mock_progress.update.assert_not_called()

    @patch("lablink_cli.commands.launch.Progress")
    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_progress_bar_not_updated_when_only_one_field_present(
        self, mock_url, mock_creds, mock_api_cls, mock_progress_cls, mock_cfg,
    ):
        """resources_total and resources_completed are independent optional
        fields — a response carrying one without the other (e.g. total=5,
        completed=None) must not render a literal "None" into the
        description."""
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_progress = MagicMock()
        mock_progress.add_task.return_value = "task-id"
        mock_progress_cls.return_value.__enter__.return_value = mock_progress

        captured = {}

        def fake_launch_vms(num_vms, on_progress=None):
            captured["on_progress"] = on_progress
            return {"status": "success", "output": ""}

        mock_api = MagicMock()
        mock_api.launch_vms.side_effect = fake_launch_vms
        mock_api_cls.return_value = mock_api

        run_launch(mock_cfg, num_vms=1)

        captured["on_progress"](None, 5)
        mock_progress.update.assert_not_called()

        captured["on_progress"](3, None)
        mock_progress.update.assert_not_called()


class TestManualLaunchNoOp:
    def test_manual_provider_prints_explanation_and_exits_zero(
        self, capsys, mock_cfg,
    ):
        mock_cfg.provider = "manual"
        # Should NOT raise and NOT touch AWS
        run_launch(mock_cfg, num_vms=5, verbose=False)
        out = capsys.readouterr().out
        assert "Manual provider" in out
        assert "lablink client register" in " ".join(out.split())

    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_manual_provider_does_not_touch_allocator(
        self, mock_url, mock_creds, mock_api_cls, mock_cfg,
    ):
        mock_cfg.provider = "manual"
        run_launch(mock_cfg, num_vms=3, verbose=False)
        mock_url.assert_not_called()
        mock_creds.assert_not_called()
        mock_api_cls.assert_not_called()


class TestRunClientDestroy:
    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_no_allocator_url_exits(
        self, mock_url, mock_creds, mock_api_cls, mock_cfg
    ):
        mock_url.return_value = ""

        with pytest.raises(SystemExit):
            run_client_destroy(mock_cfg, yes=True)

        mock_api_cls.assert_not_called()

    @patch("lablink_cli.commands.launch.typer.confirm")
    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_declining_confirmation_touches_nothing(
        self, mock_url, mock_creds, mock_api_cls, mock_confirm, mock_cfg
    ):
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_confirm.return_value = False

        run_client_destroy(mock_cfg, yes=False)

        mock_api_cls.return_value.destroy_vms.assert_not_called()

    @patch("lablink_cli.commands.launch.typer.confirm")
    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_yes_skips_the_prompt(
        self, mock_url, mock_creds, mock_api_cls, mock_confirm, mock_cfg
    ):
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_api = MagicMock()
        mock_api.destroy_vms.return_value = {"status": "success", "output": ""}
        mock_api_cls.return_value = mock_api

        run_client_destroy(mock_cfg, yes=True)

        mock_confirm.assert_not_called()
        mock_api.destroy_vms.assert_called_once()
        assert callable(mock_api.destroy_vms.call_args.kwargs["on_progress"])

    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_success_prints_destroy_summary(
        self, mock_url, mock_creds, mock_api_cls, mock_cfg, capsys
    ):
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_api = MagicMock()
        mock_api.destroy_vms.return_value = {
            "status": "success",
            "output": "Destroy complete! Resources: 4 destroyed.",
        }
        mock_api_cls.return_value = mock_api

        run_client_destroy(mock_cfg, yes=True)

        out = " ".join(capsys.readouterr().out.split())
        assert "client VMs destroyed" in out
        assert "Resources: 4 destroyed" in out

    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_verbose_prints_raw_output(
        self, mock_url, mock_creds, mock_api_cls, mock_cfg, capsys
    ):
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_api = MagicMock()
        mock_api.destroy_vms.return_value = {
            "status": "success",
            "output": "aws_instance.x: Destroying...",
        }
        mock_api_cls.return_value = mock_api

        run_client_destroy(mock_cfg, yes=True, verbose=True)

        out = " ".join(capsys.readouterr().out.split())
        assert "aws_instance.x: Destroying" in out
        assert "Pass --verbose" not in out

    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_no_vms_launched_is_not_a_failure(
        self, mock_url, mock_creds, mock_api_cls, mock_cfg, capsys
    ):
        """Nothing launched means nothing to destroy — idempotent, exit 0."""
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_api = MagicMock()
        mock_api.destroy_vms.side_effect = AllocatorNotFoundError(
            "tfvars does not exist — no client VMs were launched"
        )
        mock_api_cls.return_value = mock_api

        # Must NOT raise.
        run_client_destroy(mock_cfg, yes=True)

        out = " ".join(capsys.readouterr().out.split())
        assert "No client VMs were launched" in out

    @pytest.mark.parametrize(
        "exc",
        [
            AllocatorAuthError("Authentication failed"),
            AllocatorUnavailableError("connection refused"),
            AllocatorError("An operation is already in progress (job #7)"),
        ],
    )
    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_failures_exit_one(
        self, mock_url, mock_creds, mock_api_cls, mock_cfg, exc
    ):
        mock_url.return_value = "http://1.2.3.4"
        mock_creds.return_value = ("admin", "password")
        mock_api = MagicMock()
        mock_api.destroy_vms.side_effect = exc
        mock_api_cls.return_value = mock_api

        with pytest.raises(SystemExit) as excinfo:
            run_client_destroy(mock_cfg, yes=True)

        assert excinfo.value.code == 1


class TestManualDestroyNoOp:
    @patch("lablink_cli.commands.launch.AllocatorAPI")
    @patch("lablink_cli.commands.launch.resolve_admin_credentials")
    @patch("lablink_cli.commands.launch.get_allocator_url")
    def test_manual_provider_points_at_unregister_and_touches_nothing(
        self, mock_url, mock_creds, mock_api_cls, mock_cfg, capsys
    ):
        mock_cfg.provider = "manual"

        run_client_destroy(mock_cfg, yes=True)

        out = " ".join(capsys.readouterr().out.split())
        assert "Manual provider" in out
        assert "lablink client unregister" in out
        mock_url.assert_not_called()
        mock_creds.assert_not_called()
        mock_api_cls.assert_not_called()
