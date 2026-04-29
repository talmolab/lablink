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
    """Return the path to ~/.aws/credentials."""
    return Path(os.environ.get("HOME", str(Path.home()))) / ".aws" / "credentials"


def sso_cache_path(start_url: str) -> Path:
    """Return the AWS-CLI-compatible cache path for an SSO access token."""
    home = Path(os.environ.get("HOME", str(Path.home())))
    digest = hashlib.sha1(start_url.encode("utf-8")).hexdigest()
    return home / ".aws" / "sso" / "cache" / f"{digest}.json"
