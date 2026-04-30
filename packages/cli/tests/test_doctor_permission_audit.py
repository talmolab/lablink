"""Tests for the proactive permission audit in `lablink doctor`."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from lablink_cli.commands.doctor import _check_lablink_permissions


def test_audit_returns_pass_when_all_actions_allowed():
    fake_session = MagicMock()
    fake_iam = MagicMock()
    fake_session.client.side_effect = lambda svc: (
        MagicMock(
            get_caller_identity=lambda: {
                "Arn": (
                    "arn:aws:sts::123456789012:assumed-role/"
                    "AWSReservedSSO_lablink_abc/alice"
                ),
            }
        )
        if svc == "sts"
        else fake_iam
    )
    fake_iam.simulate_principal_policy.return_value = {
        "EvaluationResults": [
            {"EvalActionName": "ec2:DescribeInstances", "EvalDecision": "allowed"},
            {"EvalActionName": "iam:GetRole", "EvalDecision": "allowed"},
        ]
    }
    with patch(
        "lablink_cli.commands.doctor.get_session", return_value=fake_session,
        create=True,
    ):
        result = _check_lablink_permissions(region="us-east-1")

    assert result["status"] == "pass"


def test_audit_reports_denied_actions_with_update_policy_hint():
    fake_session = MagicMock()
    fake_iam = MagicMock()
    fake_session.client.side_effect = lambda svc: (
        MagicMock(
            get_caller_identity=lambda: {
                "Arn": (
                    "arn:aws:sts::123456789012:assumed-role/"
                    "AWSReservedSSO_lablink_abc/alice"
                ),
            }
        )
        if svc == "sts"
        else fake_iam
    )
    fake_iam.simulate_principal_policy.return_value = {
        "EvaluationResults": [
            {"EvalActionName": "ec2:DescribeInstances", "EvalDecision": "allowed"},
            {
                "EvalActionName": "budgets:DescribeBudgets",
                "EvalDecision": "implicitDeny",
            },
        ]
    }
    with patch(
        "lablink_cli.commands.doctor.get_session", return_value=fake_session,
        create=True,
    ):
        result = _check_lablink_permissions(region="us-east-1")

    assert result["status"] == "fail"
    assert "budgets:DescribeBudgets" in result["detail"]
    assert "lablink login --update-policy" in result["detail"]


def test_audit_skipped_when_not_on_lablink_sso_role():
    """If the user has env-var creds (no SSO profile), warn and skip the audit."""
    fake_session = MagicMock()
    fake_session.client.return_value.get_caller_identity.return_value = {
        "Arn": "arn:aws:iam::123456789012:user/alice",  # IAM user, not SSO
    }
    with patch(
        "lablink_cli.commands.doctor.get_session", return_value=fake_session,
        create=True,
    ):
        result = _check_lablink_permissions(region="us-east-1")
    assert result["status"] == "warn"
    assert "Identity Center" in result["detail"]


def test_audit_skipped_when_not_logged_in():
    """If get_session raises NotLoggedInError, the audit is warn-skipped."""
    from lablink_cli.auth.credentials import NotLoggedInError

    with patch(
        "lablink_cli.commands.doctor.get_session",
        side_effect=NotLoggedInError("not signed in"),
        create=True,
    ):
        result = _check_lablink_permissions(region="us-east-1")
    assert result["status"] == "warn"
    detail = result["detail"]
    assert "Not signed in" in detail or "not signed in" in detail.lower()
