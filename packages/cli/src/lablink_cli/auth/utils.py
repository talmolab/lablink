"""Shared path/utility helpers for the auth module.

Resolves locations of AWS CLI-compatible config and SSO token caches
in one place so other auth modules (credentials, sso_flow, bootstrap,
login) can read and write the same files without redefining the
resolution logic.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def aws_config_path() -> Path:
    """Return the path to ~/.aws/config, honoring AWS_CONFIG_FILE."""
    explicit = os.environ.get("AWS_CONFIG_FILE")
    if explicit:
        return Path(explicit)
    return Path(os.environ.get("HOME", str(Path.home()))) / ".aws" / "config"


def aws_credentials_path() -> Path:
    """Return the path to ~/.aws/credentials, honoring AWS_SHARED_CREDENTIALS_FILE.

    Matches boto3 / AWS CLI v2 resolution: the env var, when set, points at
    the credentials file directly; otherwise fall back to ``$HOME/.aws/credentials``.
    """
    explicit = os.environ.get("AWS_SHARED_CREDENTIALS_FILE")
    if explicit:
        return Path(explicit)
    return Path(os.environ.get("HOME", str(Path.home()))) / ".aws" / "credentials"


def sso_cache_path(sso_session_name: str) -> Path:
    """Return the AWS-CLI-compatible cache path for an SSO access token.

    AWS CLI v2 hashes the sso-session name (modern `[sso-session NAME]`
    config) to derive the cache filename, not the start URL. Earlier
    legacy configs used the start URL — but since we always write
    `[sso-session lablink]` blocks, we always pass the session name.
    """
    home = Path(os.environ.get("HOME", str(Path.home())))
    digest = hashlib.sha1(sso_session_name.encode("utf-8")).hexdigest()
    return home / ".aws" / "sso" / "cache" / f"{digest}.json"
