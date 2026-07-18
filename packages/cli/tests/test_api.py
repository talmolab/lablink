"""Tests for lablink_cli.api AllocatorAPI."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from lablink_cli.api import (
    AllocatorAPI,
    AllocatorAuthError,
    AllocatorError,
    AllocatorNotFoundError,
    AllocatorOperationTimeout,
    AllocatorUnavailableError,
)


def _make_api(
    base_url: str = "https://allocator.example.com",
    admin_user: str = "admin",
    admin_password: str = "secret",
    ssl_provider: str = "none",
) -> AllocatorAPI:
    return AllocatorAPI(base_url, admin_user, admin_password, ssl_provider)


def _mock_response(body: dict) -> MagicMock:
    """Build a mock urlopen() context-manager response for a JSON body."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(body).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestDestroyVms:
    @patch("lablink_cli.api.time.sleep")
    @patch("lablink_cli.api.urlopen")
    def test_success(self, mock_urlopen, mock_sleep):
        mock_urlopen.side_effect = [
            _mock_response({"job_id": 7, "status": "queued"}),
            _mock_response(
                {"id": 7, "status": "succeeded", "output": "Destroy complete!"}
            ),
        ]

        api = _make_api()
        result = api.destroy_vms()

        assert result == {"status": "success", "output": "Destroy complete!"}
        submit_req = mock_urlopen.call_args_list[0][0][0]
        assert submit_req.full_url == "https://allocator.example.com/destroy"
        assert submit_req.method == "POST"
        assert "Basic" in submit_req.get_header("Authorization")
        poll_req = mock_urlopen.call_args_list[1][0][0]
        assert (
            poll_req.full_url
            == "https://allocator.example.com/api/operations/7"
        )
        mock_sleep.assert_not_called()

    @patch("lablink_cli.api.time.sleep")
    @patch("lablink_cli.api.urlopen")
    def test_polls_while_queued_and_running(self, mock_urlopen, mock_sleep):
        mock_urlopen.side_effect = [
            _mock_response({"job_id": 7, "status": "queued"}),
            _mock_response({"id": 7, "status": "queued"}),
            _mock_response({"id": 7, "status": "running"}),
            _mock_response(
                {"id": 7, "status": "succeeded", "output": "done"}
            ),
        ]

        api = _make_api()
        result = api.destroy_vms()

        assert result == {"status": "success", "output": "done"}
        assert mock_urlopen.call_count == 4
        assert mock_sleep.call_count == 2

    @patch("lablink_cli.api.time.sleep")
    @patch("lablink_cli.api.urlopen")
    def test_401_on_submit_raises_auth_error(self, mock_urlopen, mock_sleep):
        mock_urlopen.side_effect = HTTPError(
            "url", 401, "Unauthorized", {}, None
        )
        api = _make_api()
        with pytest.raises(AllocatorAuthError):
            api.destroy_vms()

    @patch("lablink_cli.api.time.sleep")
    @patch("lablink_cli.api.urlopen")
    def test_no_vms_launched_raises_not_found(self, mock_urlopen, mock_sleep):
        """The 'no terraform.runtime.tfvars' failure now surfaces as a
        failed operation rather than a synchronous 404 — destroy_vms()
        must still map it to AllocatorNotFoundError so deploy.py's
        existing handling (continue tearing down the allocator) applies
        unchanged."""
        mock_urlopen.side_effect = [
            _mock_response({"job_id": 9, "status": "queued"}),
            _mock_response(
                {
                    "id": 9,
                    "status": "failed",
                    "error": (
                        "tfvars does not exist — no client VMs were "
                        "launched"
                    ),
                }
            ),
        ]
        api = _make_api()
        with pytest.raises(AllocatorNotFoundError):
            api.destroy_vms()

    @patch("lablink_cli.api.time.sleep")
    @patch("lablink_cli.api.urlopen")
    def test_terraform_failure_raises_allocator_error(
        self, mock_urlopen, mock_sleep
    ):
        mock_urlopen.side_effect = [
            _mock_response({"job_id": 9, "status": "queued"}),
            _mock_response(
                {
                    "id": 9,
                    "status": "failed",
                    "error": "Terraform failed: some real error",
                }
            ),
        ]
        api = _make_api()
        with pytest.raises(AllocatorError, match="some real error"):
            api.destroy_vms()

    @patch("lablink_cli.api.time.sleep")
    @patch("lablink_cli.api.urlopen")
    def test_interrupted_raises_allocator_error(self, mock_urlopen, mock_sleep):
        mock_urlopen.side_effect = [
            _mock_response({"job_id": 9, "status": "queued"}),
            _mock_response({"id": 9, "status": "interrupted"}),
        ]
        api = _make_api()
        with pytest.raises(AllocatorError, match="interrupted"):
            api.destroy_vms()

    @patch("lablink_cli.api.time.sleep")
    @patch("lablink_cli.api.urlopen")
    def test_502_on_submit_raises_unavailable(self, mock_urlopen, mock_sleep):
        mock_urlopen.side_effect = HTTPError(
            "url", 502, "Bad Gateway", {}, None
        )
        api = _make_api()
        with pytest.raises(AllocatorUnavailableError):
            api.destroy_vms()

    @patch("lablink_cli.api.time.sleep")
    @patch("lablink_cli.api.urlopen")
    def test_connection_error_on_submit_raises_unavailable(
        self, mock_urlopen, mock_sleep
    ):
        mock_urlopen.side_effect = URLError("connection refused")
        api = _make_api()
        with pytest.raises(AllocatorUnavailableError):
            api.destroy_vms()

    @patch("lablink_cli.api.time.sleep")
    @patch("lablink_cli.api.urlopen")
    def test_transient_poll_failure_is_retried(self, mock_urlopen, mock_sleep):
        """A connection error during a POLL (not the initial submit)
        must not abort the operation — the job keeps running
        server-side regardless of whether our poll request succeeds."""
        mock_urlopen.side_effect = [
            _mock_response({"job_id": 7, "status": "queued"}),
            URLError("temporary network blip"),
            _mock_response(
                {"id": 7, "status": "succeeded", "output": "done"}
            ),
        ]
        api = _make_api()
        result = api.destroy_vms()
        assert result == {"status": "success", "output": "done"}
        assert mock_urlopen.call_count == 3

    @patch("lablink_cli.api.time.monotonic")
    @patch("lablink_cli.api.time.sleep")
    @patch("lablink_cli.api.urlopen")
    def test_poll_timeout_raises(self, mock_urlopen, mock_sleep, mock_monotonic):
        mock_urlopen.side_effect = [
            _mock_response({"job_id": 7, "status": "queued"}),
            _mock_response({"id": 7, "status": "running"}),
        ]
        # First monotonic() call establishes the deadline (t=0); the
        # second (checked after the one poll above) is already past it.
        mock_monotonic.side_effect = [0.0, 1801.0]
        api = _make_api()
        with pytest.raises(AllocatorOperationTimeout):
            api.destroy_vms()

    @patch("lablink_cli.api.time.sleep")
    @patch("lablink_cli.api.urlopen")
    def test_self_signed_ssl(self, mock_urlopen, mock_sleep):
        mock_urlopen.side_effect = [
            _mock_response({"job_id": 1, "status": "queued"}),
            _mock_response({"id": 1, "status": "succeeded", "output": ""}),
        ]
        api = _make_api(ssl_provider="self_signed")
        api.destroy_vms()
        assert mock_urlopen.call_count == 2


class TestLaunchVms:
    @patch("lablink_cli.api.time.sleep")
    @patch("lablink_cli.api.urlopen")
    def test_success(self, mock_urlopen, mock_sleep):
        mock_urlopen.side_effect = [
            _mock_response({"job_id": 3, "status": "queued"}),
            _mock_response(
                {"id": 3, "status": "succeeded", "output": "apply success"}
            ),
        ]
        api = _make_api()
        result = api.launch_vms(2)

        assert result == {"status": "success", "output": "apply success"}
        submit_req = mock_urlopen.call_args_list[0][0][0]
        assert (
            submit_req.full_url
            == "https://allocator.example.com/api/launch"
        )
        assert (
            submit_req.get_header("Content-type")
            == "application/x-www-form-urlencoded"
        )
        assert submit_req.data == b"num_vms=2"

    @patch("lablink_cli.api.time.sleep")
    @patch("lablink_cli.api.urlopen")
    def test_failure_raises_allocator_error(self, mock_urlopen, mock_sleep):
        mock_urlopen.side_effect = [
            _mock_response({"job_id": 3, "status": "queued"}),
            _mock_response(
                {
                    "id": 3,
                    "status": "failed",
                    "error": (
                        "Security-group audit refused the plan: bad"
                    ),
                }
            ),
        ]
        api = _make_api()
        with pytest.raises(AllocatorError, match="Security-group audit"):
            api.launch_vms(2)

    @patch("lablink_cli.api.time.sleep")
    @patch("lablink_cli.api.urlopen")
    def test_409_raises_allocator_error(self, mock_urlopen, mock_sleep):
        """A conflict (another operation already in progress) surfaces
        as a plain HTTPError from the submit call — the existing
        _handle_http_error fallback already produces a clear message."""
        error_body = json.dumps(
            {
                "status": "error",
                "error": "An operation is already in progress (job #5)",
                "job_id": 5,
            }
        ).encode()
        from io import BytesIO

        mock_urlopen.side_effect = HTTPError(
            "url", 409, "Conflict", {}, BytesIO(error_body)
        )
        api = _make_api()
        with pytest.raises(AllocatorError, match="already in progress"):
            api.launch_vms(1)
