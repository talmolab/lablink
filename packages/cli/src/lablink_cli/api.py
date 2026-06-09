"""HTTP client for the LabLink allocator service."""

from __future__ import annotations

import base64
import json
import ssl
from typing import NoReturn
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from importlib.metadata import version as _pkg_version

    _CLI_VERSION = _pkg_version("lablink-cli")
except Exception:  # pragma: no cover - package metadata unavailable
    _CLI_VERSION = "0.0.0"

# Product User-Agent for all CLI HTTP requests. urllib's default
# "Python-urllib/x.y" is blocked with HTTP 403 by Cloudflare-proxied
# allocators, so every Request must identify itself with this instead.
USER_AGENT = f"lablink-cli/{_CLI_VERSION}"


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
        req.add_header("User-Agent", USER_AGENT)
        req.add_header("Authorization", self._auth_header)
        req.add_header("Accept", "application/json")

        try:
            # S310: URL scheme is operator-supplied by design (allocator base
            # URL from the CLI config); skipping the scheme allowlist check.
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

    def _handle_http_error(self, e: HTTPError) -> NoReturn:
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


class AllocatorConflictError(AllocatorError):
    """409 Conflict (already-registered machine_identity)."""


class RegistrationClient:
    """HTTP client for the registration endpoint (Bearer auth, no admin creds).

    Used by `lablink client register` on the BYO box. Unlike AllocatorAPI which
    requires admin Basic auth, RegistrationClient authenticates with the
    bootstrap register_token only — which is what a BYO box has at
    onboarding time.
    """

    def __init__(
        self,
        base_url: str,
        register_token: str,
        *,
        ssl_provider: str = "none",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._auth_header = f"Bearer {register_token}"
        self._ssl_ctx = ssl.create_default_context()
        if ssl_provider == "self_signed":
            self._ssl_ctx.check_hostname = False
            self._ssl_ctx.verify_mode = ssl.CERT_NONE

    def register(
        self,
        *,
        hostname: str,
        machine_identity: str,
        lan_ip: str,
        gpu_present: bool,
        gpu_model: str | None,
    ) -> dict:
        """POST /api/v1/clients/register; return parsed JSON.

        Raises AllocatorAuthError on 401, AllocatorConflictError on 409,
        AllocatorUnavailableError on connection failure, AllocatorError
        on other HTTP error codes / malformed response.
        """
        body = {
            "hostname": hostname,
            "machine_identity": machine_identity,
            "provider": "manual",
            "endpoint_url": f"http://{lan_ip}:7070",
            "provider_metadata": {"lan_ip": lan_ip},
            "gpu_present": gpu_present,
            "gpu_model": gpu_model,
        }
        return self._post("/api/v1/clients/register", body)

    def _post(self, path: str, body: dict) -> dict:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode()
        req = Request(url, data=data, method="POST")
        req.add_header("User-Agent", USER_AGENT)
        req.add_header("Authorization", self._auth_header)
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")

        try:
            # S310: URL scheme is operator-supplied by design (allocator base
            # URL from `--allocator-url`); skipping the scheme allowlist check.
            with urlopen(req, timeout=60, context=self._ssl_ctx) as resp:  # noqa: S310
                raw = resp.read().decode()
        except HTTPError as e:
            self._handle_http_error(e)
        except URLError as e:
            raise AllocatorUnavailableError(str(e.reason)) from e

        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            raise AllocatorError("Allocator returned non-JSON response") from e

    def _handle_http_error(self, e: HTTPError) -> NoReturn:
        try:
            err_body = json.loads(e.read().decode())
            msg = err_body.get("error", str(e))
        except (json.JSONDecodeError, UnicodeDecodeError):
            msg = str(e)

        if e.code == 401:
            raise AllocatorAuthError(
                "Registration rejected — register_token may be stale "
                "(allocator restarts mint a new one) or wrong."
            ) from e
        if e.code == 409:
            raise AllocatorConflictError(
                "Already registered with this machine_identity. "
                "Re-register with --force or pass a different "
                "--machine-identity."
            ) from e
        if e.code == 400:
            raise AllocatorError(f"Bad request: {msg}") from e
        raise AllocatorError(f"HTTP {e.code}: {msg}") from e
