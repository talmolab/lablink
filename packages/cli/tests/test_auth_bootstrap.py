"""Tests for auth.bootstrap — first-time Identity Center setup."""

from __future__ import annotations

import configparser
from unittest.mock import patch

import pytest

from lablink_cli.auth import bootstrap


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / ".aws" / "config"))
    return tmp_path


def test_extract_region_from_start_url():
    url = "https://d-9067abc123.awsapps.com/start"
    # Default fallback when the URL doesn't carry region info.
    assert bootstrap._extract_region_from_url(url) is None


def test_validate_start_url_accepts_well_formed():
    assert bootstrap._is_valid_sso_start_url(
        "https://d-9067abc123.awsapps.com/start"
    )
    assert bootstrap._is_valid_sso_start_url(
        "https://my-org.awsapps.com/start"
    )


def test_validate_start_url_rejects_garbage():
    assert not bootstrap._is_valid_sso_start_url("not-a-url")
    assert not bootstrap._is_valid_sso_start_url("https://example.com/")
    assert not bootstrap._is_valid_sso_start_url("")


def test_write_aws_config_creates_sso_session_and_profile_blocks(fake_home):
    cfg = bootstrap.SSOBootstrapResult(
        start_url="https://d-test.awsapps.com/start",
        sso_region="us-east-1",
        permission_set_name="lablink",
        deployment_region="us-west-2",
    )
    bootstrap._write_aws_config(cfg)

    config_path = fake_home / ".aws" / "config"
    assert config_path.exists()
    parser = configparser.ConfigParser()
    parser.read(config_path)

    assert "sso-session lablink" in parser.sections()
    assert (
        parser.get("sso-session lablink", "sso_start_url")
        == "https://d-test.awsapps.com/start"
    )
    assert parser.get("sso-session lablink", "sso_region") == "us-east-1"

    assert "profile lablink" in parser.sections()
    assert parser.get("profile lablink", "sso_session") == "lablink"
    assert parser.get("profile lablink", "sso_role_name") == "lablink"
    assert parser.get("profile lablink", "region") == "us-west-2"


def test_write_aws_config_preserves_other_profiles(fake_home):
    """Bootstrap must not clobber unrelated [profile X] blocks."""
    config_path = fake_home / ".aws" / "config"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "[profile work]\n"
        "region = eu-west-1\n"
        "aws_access_key_id = AKIATEST\n"
    )

    cfg = bootstrap.SSOBootstrapResult(
        start_url="https://d-test.awsapps.com/start",
        sso_region="us-east-1",
        permission_set_name="lablink",
        deployment_region="us-east-1",
    )
    bootstrap._write_aws_config(cfg)

    parser = configparser.ConfigParser()
    parser.read(config_path)
    assert "profile work" in parser.sections()
    assert parser.get("profile work", "region") == "eu-west-1"
    assert "profile lablink" in parser.sections()


def test_state_file_round_trip(fake_home):
    state = bootstrap.BootstrapState(
        sso_start_url="https://d-test.awsapps.com/start",
        sso_region="us-east-1",
        permission_set_name="lablink",
        steps_complete=["enable", "permission_set"],
    )
    state.save()
    loaded = bootstrap.BootstrapState.load()
    assert loaded == state
    # Confirm state was written under the fake HOME, not real ~/.lablink
    assert (fake_home / ".lablink" / "bootstrap-state.json").exists()


def test_load_state_returns_none_when_missing(fake_home):
    assert not (fake_home / ".lablink" / "bootstrap-state.json").exists()
    assert bootstrap.BootstrapState.load() is None


def test_load_state_returns_none_when_corrupt(fake_home):
    state_path = fake_home / ".lablink" / "bootstrap-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("not valid json {{{")
    assert bootstrap.BootstrapState.load() is None


def test_clear_state_removes_file(fake_home):
    state = bootstrap.BootstrapState(
        sso_start_url="x", sso_region="y", permission_set_name="z",
        steps_complete=["enable"],
    )
    state.save()
    state_file = fake_home / ".lablink" / "bootstrap-state.json"
    assert state_file.exists()
    bootstrap.BootstrapState.clear()
    assert not state_file.exists()
    assert bootstrap.BootstrapState.load() is None


def test_copy_to_clipboard_falls_back_to_file_when_pyperclip_unavailable(
    fake_home,
):
    with patch(
        "lablink_cli.auth.bootstrap._pyperclip_copy",
        side_effect=Exception("no clip"),
    ):
        path = bootstrap._copy_to_clipboard("policy json contents")

    # Fallback writes the JSON to a file in ~/.lablink and returns the path
    assert path is not None
    assert path.exists()
    assert path.read_text() == "policy json contents"
    # And the path is inside the fake HOME, not the real one
    assert fake_home in path.parents


def test_run_bootstrap_writes_config_after_user_completes_console_steps(
    fake_home, monkeypatch
):
    """Smoke test: run_bootstrap fully drives the flow with mocked I/O."""
    # User pastes a valid SSO Start URL, hits Enter for region default,
    # accepts default permission-set name, and presses Enter at each prompt.
    inputs = iter(
        [
            "",  # Press Enter to open Identity Center console
            "https://d-9067abc123.awsapps.com/start",  # SSO Start URL
            "us-east-1",  # SSO region
            "",  # Press Enter to open create permission set page
            "lablink",  # Permission set name
            "",  # Press Enter once permission set created
            "",  # Press Enter to open assign user page
            "",  # Press Enter once assigned
        ]
    )
    monkeypatch.setattr("builtins.input", lambda *a, **kw: next(inputs))
    monkeypatch.setattr(
        "lablink_cli.auth.bootstrap.typer.prompt",
        lambda *a, **kw: next(inputs),
    )
    monkeypatch.setattr(
        "lablink_cli.auth.bootstrap.webbrowser.open", lambda *a, **kw: True
    )
    monkeypatch.setattr(
        "lablink_cli.auth.bootstrap._copy_to_clipboard", lambda payload: None
    )

    result = bootstrap.run_bootstrap(deployment_region="us-east-1")

    assert result.start_url == "https://d-9067abc123.awsapps.com/start"
    assert result.sso_region == "us-east-1"
    assert result.permission_set_name == "lablink"

    config_path = fake_home / ".aws" / "config"
    assert config_path.exists()
    parser = configparser.ConfigParser()
    parser.read(config_path)
    assert "sso-session lablink" in parser.sections()


def test_run_bootstrap_resumes_from_saved_state(fake_home, monkeypatch):
    """If state shows enable+permission_set complete, only assign + write is needed."""
    state_file = fake_home / ".lablink" / "bootstrap-state.json"
    bootstrap.BootstrapState(
        sso_start_url="https://d-9067abc123.awsapps.com/start",
        sso_region="us-east-1",
        permission_set_name="lablink",
        steps_complete=["enable", "permission_set"],
    ).save()
    assert state_file.exists()

    inputs = iter(
        [
            "",  # Press Enter to open assign user page
            "",  # Press Enter once assigned
        ]
    )
    monkeypatch.setattr("builtins.input", lambda *a, **kw: next(inputs))
    monkeypatch.setattr(
        "lablink_cli.auth.bootstrap.webbrowser.open", lambda *a, **kw: True
    )

    result = bootstrap.run_bootstrap(deployment_region="us-east-1")
    assert result.start_url == "https://d-9067abc123.awsapps.com/start"
    # State should be cleared after completion
    assert bootstrap.BootstrapState.load() is None
