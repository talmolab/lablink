"""Tests for the `lablink login` command."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from lablink_cli.app import app

runner = CliRunner()


def test_login_runs_bootstrap_when_no_sso_profile():
    with (
        patch("lablink_cli.commands.login.is_logged_in", return_value=False),
        patch(
            "lablink_cli.commands.login._has_sso_profile", return_value=False
        ),
        patch("lablink_cli.commands.login.run_bootstrap") as mock_bootstrap,
        patch("lablink_cli.commands.login.run_steady_state") as mock_steady,
    ):
        mock_bootstrap.return_value = MagicMock(
            start_url="https://d-test.awsapps.com/start",
            sso_region="us-east-1",
            permission_set_name="lablink",
            deployment_region="us-east-1",
        )
        result = runner.invoke(app, ["login"])

    assert result.exit_code == 0
    mock_bootstrap.assert_called_once()
    mock_steady.assert_called_once()


def test_login_skips_bootstrap_when_sso_profile_exists():
    with (
        patch("lablink_cli.commands.login.is_logged_in", return_value=False),
        patch("lablink_cli.commands.login._has_sso_profile", return_value=True),
        patch("lablink_cli.commands.login.run_bootstrap") as mock_bootstrap,
        patch("lablink_cli.commands.login.run_steady_state") as mock_steady,
    ):
        result = runner.invoke(app, ["login"])

    assert result.exit_code == 0
    mock_bootstrap.assert_not_called()
    mock_steady.assert_called_once()


def test_login_already_logged_in_prompts_before_relogin():
    with (
        patch("lablink_cli.commands.login.is_logged_in", return_value=True),
        patch("lablink_cli.commands.login._token_expiry_human", return_value="4h 12m"),
        patch("lablink_cli.commands.login.run_steady_state") as mock_steady,
    ):
        # User answers "n" — should not re-login
        result = runner.invoke(app, ["login"], input="n\n")

    assert result.exit_code == 0
    assert "Already signed in" in result.stdout
    mock_steady.assert_not_called()


def test_login_already_logged_in_relogs_when_user_confirms():
    with (
        patch("lablink_cli.commands.login.is_logged_in", return_value=True),
        patch("lablink_cli.commands.login._token_expiry_human", return_value="4h 12m"),
        patch("lablink_cli.commands.login._has_sso_profile", return_value=True),
        patch("lablink_cli.commands.login.run_steady_state") as mock_steady,
    ):
        result = runner.invoke(app, ["login"], input="y\n")

    assert result.exit_code == 0
    mock_steady.assert_called_once()


def test_login_update_policy_flag_reprints_deeplink():
    with (
        patch("lablink_cli.commands.login._copy_to_clipboard") as mock_copy,
        patch("lablink_cli.commands.login.webbrowser.open"),
    ):
        result = runner.invoke(app, ["login", "--update-policy"])

    assert result.exit_code == 0
    assert "Permission set" in result.stdout
    mock_copy.assert_called_once()
