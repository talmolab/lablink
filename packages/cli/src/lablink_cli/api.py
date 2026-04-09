"""HTTP client for the LabLink allocator service."""

from __future__ import annotations

import base64
import json
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class AllocatorError(Exception):
    """Base exception for allocator API errors."""


class AllocatorAuthError(AllocatorError):
    """401 Unauthorized."""


class AllocatorNotFoundError(AllocatorError):
    """404 Not Found (no client VMs launched)."""


class AllocatorUnavailableError(AllocatorError):
    """502 Bad Gateway or connection failure."""


class AllocatorAPI:
    """HTTP client for the allocator service."""

    def __init__(
        self,
        base_url: str,
        admin_user: str,
        admin_password: str,
        ssl_provider: str = "none",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._auth_header = "Basic " + base64.b64encode(
            f"{admin_user}:{admin_password}".encode()
        ).decode()

        self._ssl_ctx = ssl.create_default_context()
        if ssl_provider == "self_signed":
            self._ssl_ctx.check_hostname = False
            self._ssl_ctx.verify_mode = ssl.CERT_NONE

    def destroy_vms(self) -> dict | None:
        """POST /destroy to tear down client VMs."""
        return self._request("POST", "/destroy")

    def _request(
        self,
        method: str,
        path: str,
        data: bytes | None = b"",
    ) -> dict | None:
        """Send an HTTP request to the allocator."""
        url = f"{self.base_url}{path}"
        req = Request(url, data=data, method=method)
        req.add_header("Authorization", self._auth_header)
        req.add_header("Accept", "application/json")

        try:
            with urlopen(req, timeout=1800, context=self._ssl_ctx) as resp:  # noqa: S310
                raw = resp.read().decode()
        except HTTPError as e:
            self._handle_http_error(e)
        except URLError as e:
            raise AllocatorUnavailableError(str(e.reason)) from e

        try:
            body = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None

        if isinstance(body, dict) and body.get("status") == "error":
            raise AllocatorError(
                body.get("error", "unknown error")
            )

        return body

    def _handle_http_error(self, e: HTTPError) -> None:
        """Translate HTTPError to typed exception."""
        if e.code == 401:
            raise AllocatorAuthError("Authentication failed") from e
        if e.code == 404:
            raise AllocatorNotFoundError(
                "No client VMs found"
            ) from e
        if e.code == 502:
            raise AllocatorUnavailableError(
                "Allocator is unhealthy (502)"
            ) from e

        try:
            body = json.loads(e.read().decode())
            msg = body.get("error", str(e))
        except (json.JSONDecodeError, UnicodeDecodeError):
            msg = str(e)

        raise AllocatorError(
            f"HTTP {e.code}: {msg}"
        ) from e
