"""Shared HTTP utilities for LabLink client services."""

import os


def sanitize_url(url: str) -> str:
    """Sanitize a URL by removing trailing slashes and stray dots.

    Handles cases like:
      - http://.lablink.sleap.ai -> http://lablink.sleap.ai
      - https://.lablink.sleap.ai -> https://lablink.sleap.ai
      - .lablink.sleap.ai -> lablink.sleap.ai
      - http://example.com/ -> http://example.com
    """
    url = url.rstrip("/")
    url = url.replace("://.", "://")
    if url.startswith("."):
        url = url[1:]
    return url


def get_auth_headers(token: str = "") -> dict:
    """Build HTTP headers with optional Bearer token auth."""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def get_client_env(cfg) -> tuple:
    """Read common client environment variables with config fallback.

    Returns:
        (base_url, client_secret, vm_name) tuple.

    Raises:
        RuntimeError: If CLIENT_SECRET is not set.
    """
    allocator_url = os.getenv("ALLOCATOR_URL")
    if allocator_url:
        base_url = sanitize_url(allocator_url)
    else:
        base_url = f"http://{cfg.allocator.host}:{cfg.allocator.port}"

    client_secret = os.environ.get("CLIENT_SECRET")
    if not client_secret:
        raise RuntimeError(
            "CLIENT_SECRET environment variable is required. "
            "Each client must be registered via /api/v1/clients/register "
            "(handled automatically by user_data.sh on AWS and "
            "`lablink register` on manual deployments)."
        )
    vm_name = os.getenv("VM_NAME")

    return base_url, client_secret, vm_name
