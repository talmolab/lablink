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
            "lablink_cli.commands.login.has_sso_profile", return_value=False
        ),
        patch("lablink_cli.commands.login.run_bootstrap") as mock_bootstrap,
        patch("lablink_cli.commands.login.run_steady_state") as mock_steady,
        patch("lablink_cli.commands.login._run_verifier_with_retry"),
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
        patch("lablink_cli.commands.login.has_sso_profile", return_value=True),
        patch("lablink_cli.commands.login.run_bootstrap") as mock_bootstrap,
        patch("lablink_cli.commands.login.run_steady_state") as mock_steady,
        patch("lablink_cli.commands.login._run_verifier_with_retry"),
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
        patch("lablink_cli.commands.login.has_sso_profile", return_value=True),
        patch("lablink_cli.commands.login.run_steady_state") as mock_steady,
        patch("lablink_cli.commands.login._run_verifier_with_retry"),
    ):
        result = runner.invoke(app, ["login"], input="y\n")

    assert result.exit_code == 0
    mock_steady.assert_called_once()


def test_login_update_policy_flag_reprints_deeplink():
    with (
        patch("lablink_cli.commands.login.copy_to_clipboard") as mock_copy,
        patch("lablink_cli.commands.login.webbrowser.open"),
    ):
        result = runner.invoke(app, ["login", "--update-policy"])

    assert result.exit_code == 0
    assert "Permission set" in result.stdout
    mock_copy.assert_called_once()


def test_login_keyboard_interrupt_during_bootstrap_prints_hint():
    """Ctrl-C during bootstrap exits with a friendly 're-run lablink login' hint."""
    with (
        patch("lablink_cli.commands.login.is_logged_in", return_value=False),
        patch("lablink_cli.commands.login.has_sso_profile", return_value=False),
        patch(
            "lablink_cli.commands.login.run_bootstrap",
            side_effect=KeyboardInterrupt,
        ),
        patch("lablink_cli.commands.login.run_steady_state") as mock_steady,
    ):
        result = runner.invoke(app, ["login"])

    assert result.exit_code == 1
    assert "Bootstrap interrupted" in result.stdout
    assert "Re-run" in result.stdout and "lablink login" in result.stdout
    mock_steady.assert_not_called()


# ------------------------------------------------------------------
# _verify_permission_set
# ------------------------------------------------------------------
def _fake_sso_session(arn="arn:aws:sts::123456789012:assumed-role/"
                          "AWSReservedSSO_lablink_abc/alice"):
    """Build a MagicMock boto3 session with sts.get_caller_identity wired."""
    fake_session = MagicMock()
    fake_iam = MagicMock()
    fake_session.client.side_effect = lambda svc: (
        MagicMock(get_caller_identity=lambda: {"Arn": arn})
        if svc == "sts" else fake_iam
    )
    return fake_session, fake_iam


def test_verifier_returns_empty_list_when_all_actions_allowed():
    from lablink_cli.commands.login import _verify_permission_set
    from lablink_cli.auth.policy import AUDIT_ACTIONS

    fake_session, fake_iam = _fake_sso_session()
    fake_iam.simulate_principal_policy.return_value = {
        "EvaluationResults": [
            {"EvalActionName": a, "EvalDecision": "allowed"}
            for a in AUDIT_ACTIONS
        ]
    }
    with patch(
        "lablink_cli.commands.login.boto3.Session", return_value=fake_session
    ):
        assert _verify_permission_set() == []


def test_verifier_maps_denied_actions_to_friendly_policy_names():
    from lablink_cli.commands.login import _verify_permission_set

    fake_session, fake_iam = _fake_sso_session()
    fake_iam.simulate_principal_policy.return_value = {
        "EvaluationResults": [
            {
                "EvalActionName": "cloudwatch:DescribeAlarms",
                "EvalDecision": "implicitDeny",
            },
            {"EvalActionName": "ec2:DescribeInstances", "EvalDecision": "allowed"},
        ]
    }
    with patch(
        "lablink_cli.commands.login.boto3.Session", return_value=fake_session
    ):
        missing = _verify_permission_set()

    assert "CloudWatchFullAccess" in missing
    assert "AmazonEC2FullAccess" not in missing


def test_verifier_treats_simulate_access_denied_as_missing_iam_full_access():
    """When IAMFullAccess is missing, simulate_principal_policy itself fails."""
    from botocore.exceptions import ClientError

    from lablink_cli.commands.login import _verify_permission_set

    fake_session, fake_iam = _fake_sso_session()
    fake_iam.simulate_principal_policy.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "denied"}},
        "SimulatePrincipalPolicy",
    )
    with patch(
        "lablink_cli.commands.login.boto3.Session", return_value=fake_session
    ):
        assert _verify_permission_set() == ["IAMFullAccess"]


def test_verifier_dedupes_when_multiple_actions_map_to_inline_policy():
    from lablink_cli.commands.login import _verify_permission_set

    fake_session, fake_iam = _fake_sso_session()
    fake_iam.simulate_principal_policy.return_value = {
        "EvaluationResults": [
            {"EvalActionName": a, "EvalDecision": "implicitDeny"}
            for a in (
                "sts:GetCallerIdentity",
                "s3:ListBucket",
                "dynamodb:DescribeTable",
            )
        ]
    }
    with patch(
        "lablink_cli.commands.login.boto3.Session", return_value=fake_session
    ):
        missing = _verify_permission_set()

    # Three inline-policy actions denied → reported once.
    assert missing == ["<inline>"]
