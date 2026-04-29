"""LabLink AWS credential resolution.

Resolution order:
  1. Identity Center profile `lablink` from ~/.aws/config (preferred)
  2. AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY environment variables
  3. ~/.aws/credentials default profile
  4. Fail with NotLoggedInError pointing at `lablink login`
"""

from __future__ import annotations

import configparser
import datetime as dt
import json
import os

import boto3

from lablink_cli.auth.utils import (
    aws_config_path,
    aws_credentials_path,
    sso_cache_path,
)

PROFILE_NAME = "lablink"
SSO_SESSION_NAME = "lablink"


class AuthError(Exception):
    """Base class for lablink auth errors."""


class NotLoggedInError(AuthError):
    """No usable AWS credentials found."""


class SSOTokenExpiredError(AuthError):
    """SSO token exists but is past expiresAt."""


def _has_sso_profile() -> bool:
    cfg_path = aws_config_path()
    if not cfg_path.exists():
        return False
    parser = configparser.ConfigParser()
    parser.read(cfg_path)
    return f"profile {PROFILE_NAME}" in parser.sections()


def _has_env_credentials() -> bool:
    return bool(
        os.environ.get("AWS_ACCESS_KEY_ID")
        and os.environ.get("AWS_SECRET_ACCESS_KEY")
    )


def _has_default_credentials_file() -> bool:
    """Return True if ~/.aws/credentials exists with a usable default profile."""
    creds_path = aws_credentials_path()
    if not creds_path.exists():
        return False
    parser = configparser.ConfigParser()
    parser.read(creds_path)
    return "default" in parser.sections()


def _read_sso_start_url() -> str | None:
    cfg_path = aws_config_path()
    if not cfg_path.exists():
        return None
    parser = configparser.ConfigParser()
    parser.read(cfg_path)
    section = f"sso-session {SSO_SESSION_NAME}"
    if section not in parser.sections():
        return None
    return parser.get(section, "sso_start_url", fallback=None)


def _token_is_valid() -> bool:
    """Return True if the cached SSO token exists and has not expired."""
    if _read_sso_start_url() is None:
        # No [sso-session lablink] block → no cache to check.
        return False
    cache_path = sso_cache_path(SSO_SESSION_NAME)
    if not cache_path.exists():
        return False
    try:
        data = json.loads(cache_path.read_text())
    except (OSError, json.JSONDecodeError):
        return False
    expires_at = data.get("expiresAt")
    if not expires_at:
        return False
    try:
        # AWS writes UTC ISO-8601 with "Z" suffix.
        expiry = dt.datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return expiry > dt.datetime.now(dt.timezone.utc)


def is_logged_in() -> bool:
    """Return True if a valid SSO token cache is present."""
    if not _has_sso_profile():
        return False
    return _token_is_valid()


def get_session(region: str | None = None) -> boto3.Session:
    """Resolve AWS credentials and return a boto3.Session.

    Raises:
        NotLoggedInError: when no SSO profile, env vars, or default creds exist.
        SSOTokenExpiredError: when the SSO profile exists but its token is expired.
    """
    if _has_sso_profile():
        if not _token_is_valid():
            raise SSOTokenExpiredError(
                "Your AWS session has expired. Run `lablink login` and try again."
            )
        return boto3.Session(profile_name=PROFILE_NAME, region_name=region)

    if _has_env_credentials() or _has_default_credentials_file():
        return boto3.Session(region_name=region)

    raise NotLoggedInError(
        "No AWS credentials found. Run `lablink login` to sign in via "
        "AWS Identity Center."
    )


def subprocess_env() -> dict[str, str]:
    """Build env vars for subprocesses (e.g. terraform) that need AWS credentials.

    Tools like Terraform's S3 backend don't auto-detect SSO profiles from
    ~/.aws/config — they only check env vars, ~/.aws/credentials, and IMDS.
    When the lablink SSO profile exists, set AWS_PROFILE=lablink so Terraform
    picks it up. When the user is on legacy access-key creds (env vars or
    ~/.aws/credentials), do nothing — those mechanisms work without help.
    """
    env = os.environ.copy()
    if _has_sso_profile():
        env["AWS_PROFILE"] = PROFILE_NAME
    return env
