"""Tests for auth.credentials.get_session and friends."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from lablink_cli.auth import credentials


def test_get_session_uses_sso_profile_when_present(tmp_path, monkeypatch):
    """If ~/.aws/config has a [profile lablink] block, get_session uses it."""
    aws_dir = tmp_path / ".aws"
    aws_dir.mkdir()
    (aws_dir / "config").write_text(
        "[sso-session lablink]\n"
        "sso_start_url = https://d-test.awsapps.com/start\n"
        "sso_region = us-east-1\n"
        "sso_registration_scopes = sso:account:access\n"
        "\n"
        "[profile lablink]\n"
        "sso_session = lablink\n"
        "sso_account_id = 123456789012\n"
        "sso_role_name = lablink\n"
        "region = us-east-1\n"
    )
    monkeypatch.setenv("AWS_CONFIG_FILE", str(aws_dir / "config"))
    monkeypatch.setenv("HOME", str(tmp_path))
    # Clear any AWS_* creds env vars so we genuinely test the SSO branch.
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

    with patch("lablink_cli.auth.credentials.boto3.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        with patch("lablink_cli.auth.credentials._token_is_valid", return_value=True):
            result = credentials.get_session(region="us-east-1")

        # Must construct with profile_name="lablink"
        mock_session_cls.assert_called_once()
        kwargs = mock_session_cls.call_args.kwargs
        assert kwargs.get("profile_name") == "lablink"
        assert kwargs.get("region_name") == "us-east-1"
        assert result is mock_session


def test_get_session_falls_back_to_env_vars_when_no_sso_profile(tmp_path, monkeypatch):
    """No SSO profile, env vars set → boto3.Session() with no profile_name."""
    aws_dir = tmp_path / ".aws"
    aws_dir.mkdir()
    (aws_dir / "config").write_text("")  # empty config
    monkeypatch.setenv("AWS_CONFIG_FILE", str(aws_dir / "config"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIATEST")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secrettest")

    with patch("lablink_cli.auth.credentials.boto3.Session") as mock_session_cls:
        mock_session_cls.return_value = MagicMock()
        credentials.get_session(region="us-east-1")
        kwargs = mock_session_cls.call_args.kwargs
        assert "profile_name" not in kwargs
        assert kwargs.get("region_name") == "us-east-1"


def test_get_session_raises_not_logged_in_when_nothing_available(tmp_path, monkeypatch):
    """No SSO profile, no env vars, no ~/.aws/credentials → NotLoggedInError."""
    aws_dir = tmp_path / ".aws"
    aws_dir.mkdir()
    (aws_dir / "config").write_text("")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(aws_dir / "config"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)

    with pytest.raises(credentials.NotLoggedInError) as exc_info:
        credentials.get_session(region="us-east-1")

    assert "lablink login" in str(exc_info.value)


def test_is_logged_in_true_when_sso_profile_with_valid_token(tmp_path, monkeypatch):
    """is_logged_in returns True when SSO profile exists and token is fresh."""
    aws_dir = tmp_path / ".aws"
    aws_dir.mkdir()
    (aws_dir / "config").write_text(
        "[sso-session lablink]\n"
        "sso_start_url = https://d-test.awsapps.com/start\n"
        "sso_region = us-east-1\n"
        "[profile lablink]\n"
        "sso_session = lablink\n"
        "region = us-east-1\n"
    )
    monkeypatch.setenv("AWS_CONFIG_FILE", str(aws_dir / "config"))
    monkeypatch.setenv("HOME", str(tmp_path))

    with patch("lablink_cli.auth.credentials._token_is_valid", return_value=True):
        assert credentials.is_logged_in() is True


def test_is_logged_in_false_when_no_sso_profile(tmp_path, monkeypatch):
    aws_dir = tmp_path / ".aws"
    aws_dir.mkdir()
    (aws_dir / "config").write_text("")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(aws_dir / "config"))
    monkeypatch.setenv("HOME", str(tmp_path))
    assert credentials.is_logged_in() is False


def test_get_session_raises_sso_token_expired_when_token_stale(tmp_path, monkeypatch):
    """Profile exists but cached token is past expiresAt → SSOTokenExpiredError."""
    aws_dir = tmp_path / ".aws"
    aws_dir.mkdir()
    (aws_dir / "config").write_text(
        "[sso-session lablink]\n"
        "sso_start_url = https://d-test.awsapps.com/start\n"
        "sso_region = us-east-1\n"
        "[profile lablink]\n"
        "sso_session = lablink\n"
        "region = us-east-1\n"
    )
    monkeypatch.setenv("AWS_CONFIG_FILE", str(aws_dir / "config"))
    monkeypatch.setenv("HOME", str(tmp_path))

    with patch("lablink_cli.auth.credentials._token_is_valid", return_value=False):
        with pytest.raises(credentials.SSOTokenExpiredError) as exc_info:
            credentials.get_session(region="us-east-1")
        assert "lablink login" in str(exc_info.value)
