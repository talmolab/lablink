"""Tests for the SSO login wrapper around `aws sso login`."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from lablink_cli.auth import sso_flow


@pytest.fixture()
def sso_config():
    return sso_flow.SSOConfig(
        start_url="https://d-test.awsapps.com/start",
        region="us-east-1",
    )


def _write_token_cache(tmp_path, start_url: str, payload: dict) -> None:
    """Helper: write an AWS-CLI-style token cache file at the expected path."""
    import hashlib

    cache_dir = tmp_path / ".aws" / "sso" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(start_url.encode("utf-8")).hexdigest()
    (cache_dir / f"{digest}.json").write_text(json.dumps(payload))


def test_ensure_aws_cli_installed_passes_when_aws_on_path():
    with patch("lablink_cli.auth.sso_flow.shutil.which", return_value="/usr/local/bin/aws"):
        sso_flow._ensure_aws_cli_installed()


def test_ensure_aws_cli_installed_raises_when_aws_missing():
    with patch("lablink_cli.auth.sso_flow.shutil.which", return_value=None):
        with pytest.raises(sso_flow.AWSCLINotFoundError) as exc:
            sso_flow._ensure_aws_cli_installed()
    assert "AWS CLI" in str(exc.value)


def test_login_runs_aws_sso_login_and_returns_cached_token(
    tmp_path, sso_config, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_token_cache(
        tmp_path,
        sso_config.start_url,
        {"accessToken": "TOKEN-XYZ", "expiresAt": "2099-01-01T00:00:00Z"},
    )

    with (
        patch(
            "lablink_cli.auth.sso_flow.shutil.which",
            return_value="/usr/local/bin/aws",
        ),
        patch(
            "lablink_cli.auth.sso_flow.subprocess.run",
            return_value=MagicMock(returncode=0),
        ) as mock_run,
    ):
        token = sso_flow.login(sso_config)

    assert token == "TOKEN-XYZ"
    args = mock_run.call_args.args[0]
    assert args == ["aws", "sso", "login", "--sso-session", "lablink"]


def test_login_raises_when_aws_cli_missing(sso_config):
    with patch("lablink_cli.auth.sso_flow.shutil.which", return_value=None):
        with pytest.raises(sso_flow.AWSCLINotFoundError):
            sso_flow.login(sso_config)


def test_login_raises_login_failed_on_nonzero_exit(
    tmp_path, sso_config, monkeypatch
):
    monkeypatch.setenv("HOME", str(tmp_path))
    with (
        patch(
            "lablink_cli.auth.sso_flow.shutil.which",
            return_value="/usr/local/bin/aws",
        ),
        patch(
            "lablink_cli.auth.sso_flow.subprocess.run",
            return_value=MagicMock(returncode=1),
        ),
    ):
        with pytest.raises(sso_flow.LoginFailedError) as exc:
            sso_flow.login(sso_config)
    assert "exit code 1" in str(exc.value)


def test_login_raises_login_failed_when_token_cache_missing(
    tmp_path, sso_config, monkeypatch
):
    """aws sso login returned 0 but no cache file was written."""
    monkeypatch.setenv("HOME", str(tmp_path))
    with (
        patch(
            "lablink_cli.auth.sso_flow.shutil.which",
            return_value="/usr/local/bin/aws",
        ),
        patch(
            "lablink_cli.auth.sso_flow.subprocess.run",
            return_value=MagicMock(returncode=0),
        ),
    ):
        with pytest.raises(sso_flow.LoginFailedError) as exc:
            sso_flow.login(sso_config)
    assert "does not exist" in str(exc.value)


def test_select_account_auto_picks_when_single_account(sso_config):
    mock_sso = MagicMock()
    mock_sso.list_accounts.return_value = {
        "accountList": [
            {"accountId": "111111111111", "accountName": "OnlyAcct"},
        ],
    }
    with patch("lablink_cli.auth.sso_flow.boto3.client", return_value=mock_sso):
        account_id = sso_flow.select_account(
            sso_config=sso_config, access_token="TOKEN"
        )
    assert account_id == "111111111111"


def test_select_account_prompts_when_multiple(sso_config):
    mock_sso = MagicMock()
    mock_sso.list_accounts.return_value = {
        "accountList": [
            {"accountId": "111111111111", "accountName": "Alpha"},
            {"accountId": "222222222222", "accountName": "Beta"},
        ],
    }
    with patch("lablink_cli.auth.sso_flow.boto3.client", return_value=mock_sso):
        with patch("lablink_cli.auth.sso_flow.typer.prompt", return_value="2"):
            account_id = sso_flow.select_account(
                sso_config=sso_config, access_token="TOKEN"
            )
    assert account_id == "222222222222"


def test_resolve_role_returns_lablink_when_present(sso_config):
    mock_sso = MagicMock()
    mock_sso.list_account_roles.return_value = {
        "roleList": [
            {"roleName": "OtherRole", "accountId": "111111111111"},
            {"roleName": "lablink", "accountId": "111111111111"},
        ],
    }
    with patch("lablink_cli.auth.sso_flow.boto3.client", return_value=mock_sso):
        role = sso_flow.resolve_role(
            sso_config=sso_config,
            access_token="TOKEN",
            account_id="111111111111",
            preferred_role_name="lablink",
        )
    assert role == "lablink"
