"""HTTP client for the LabLink allocator service."""

from __future__ import annotations

import base64
import json
import ssl
import time
from typing import NoReturn
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
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

# /destroy and /api/launch are async (they return a job id immediately;
# the allocator runs Terraform on a background thread). Individual
# requests (submit or poll) are fast, so a short per-request timeout
# replaces the old single-request timeouts of up to 1800s;
# _POLL_TIMEOUT_SECONDS is the new overall ceiling for how long we'll
# keep polling before giving up (matches the old ceiling).
_REQUEST_TIMEOUT_SECONDS = 30
_POLL_INTERVAL_SECONDS = 2.0
_POLL_TIMEOUT_SECONDS = 1800

# The exact message providers/aws.py's destroy_hosts raises (wrapped by
# main.py's /destroy route into a failed operation with this same text)
# when no client VMs were ever launched. Matched here so destroy_vms()
# can keep raising AllocatorNotFoundError for this one case, preserving
# the contract deploy.py's callers already handle (non-fatal — continue
# tearing down the allocator).
_NO_VMS_LAUNCHED_ERROR = (
    "tfvars does not exist — no client VMs were launched"
)


class AllocatorError(Exception):
    """Base exception for allocator API errors."""


class AllocatorAuthError(AllocatorError):
    """401 Unauthorized."""


class AllocatorNotFoundError(AllocatorError):
    """404 Not Found (no client VMs launched)."""


class AllocatorUnavailableError(AllocatorError):
    """502 Bad Gateway or connection failure."""


class AllocatorOperationTimeout(AllocatorError):
    """An operation did not reach a terminal status within the poll deadline."""


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
        """POST /destroy to tear down client VMs, then poll until the
        job reaches a terminal status.

        Returns {"status": "success", "output": <str>}. Raises
        AllocatorNotFoundError if no client VMs were ever launched
        (same as the old synchronous contract), or
        AllocatorError/AllocatorOperationTimeout otherwise.
        """
        return self._submit_and_poll("POST", "/destroy")

    def launch_vms(self, num_vms: int) -> dict | None:
        """POST /api/launch to provision num_vms new client VMs, then
        poll until the job reaches a terminal status.

        Returns {"status": "success", "output": <str>} on success.
        """
        data = urlencode({"num_vms": str(num_vms)}).encode()
        return self._submit_and_poll(
            "POST",
            "/api/launch",
            data,
            content_type="application/x-www-form-urlencoded",
        )

    def _submit_and_poll(
        self,
        method: str,
        path: str,
        data: bytes | None = b"",
        *,
        content_type: str | None = None,
    ) -> dict | None:
        """Submit an async apply/destroy job and poll GET
        /api/operations/<id> until it reaches a terminal status."""
        submitted = self._request(
            method, path, data, content_type=content_type
        )
        if not submitted or "job_id" not in submitted:
            raise AllocatorError(
                f"Unexpected response from {path}: {submitted}"
            )
        job_id = submitted["job_id"]

        deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
        while True:
            try:
                op = self._request("GET", f"/api/operations/{job_id}")
            except AllocatorUnavailableError:
                # Transient network blip while polling — the job keeps
                # running server-side regardless of whether our poll
                # request succeeds, so retry rather than abort an
                # operation that may still finish successfully.
                op = None

            if op is not None:
                status = op.get("status")
                if status == "succeeded":
                    return {
                        "status": "success",
                        "output": op.get("output") or "",
                    }
                if status in ("failed", "interrupted"):
                    error_text = (
                        op.get("error") or f"Operation #{job_id} {status}"
                    )
                    if _NO_VMS_LAUNCHED_ERROR in error_text:
                        raise AllocatorNotFoundError(error_text)
                    raise AllocatorError(error_text)

            if time.monotonic() > deadline:
                raise AllocatorOperationTimeout(
                    f"Operation #{job_id} did not finish within "
                    f"{_POLL_TIMEOUT_SECONDS}s"
                )
            time.sleep(_POLL_INTERVAL_SECONDS)

    def _request(
        self,
        method: str,
        path: str,
        data: bytes | None = None,
        *,
        content_type: str | None = None,
    ) -> dict | None:
        """Send an HTTP request to the allocator."""
        url = f"{self.base_url}{path}"
        req = Request(url, data=data, method=method)
        req.add_header("User-Agent", USER_AGENT)
        req.add_header("Authorization", self._auth_header)
        req.add_header("Accept", "application/json")
        if content_type:
            req.add_header("Content-Type", content_type)

        try:
            # S310: URL scheme is operator-supplied by design (allocator base
            # URL from the CLI config); skipping the scheme allowlist check.
            with urlopen(
                req, timeout=_REQUEST_TIMEOUT_SECONDS, context=self._ssl_ctx
            ) as resp:  # noqa: S310
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
