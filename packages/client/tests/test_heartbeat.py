"""Tests for the client-side heartbeat module."""

import subprocess
from unittest.mock import patch, MagicMock, mock_open

import pytest
import requests

from lablink_client_service import heartbeat


@pytest.fixture
def vm_env(monkeypatch):
    monkeypatch.setenv("VM_NAME", "vm-1")


def test_read_boot_id_returns_trimmed_contents():
    fake = mock_open(read_data="abc-123\n")
    with patch("builtins.open", fake):
        assert heartbeat.read_boot_id() == "abc-123"


def test_read_boot_id_returns_none_on_oserror(caplog):
    with patch("builtins.open", side_effect=OSError("permission denied")):
        result = heartbeat.read_boot_id()
    assert result is None
    assert "boot_id" in caplog.text


@patch("lablink_client_service.heartbeat.subprocess.run")
def test_sample_crd_active_true_when_pgrep_succeeds(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    assert heartbeat.sample_crd_active() is True


@patch("lablink_client_service.heartbeat.subprocess.run")
def test_sample_crd_active_false_when_pgrep_fails(mock_run):
    mock_run.return_value = MagicMock(returncode=1)
    assert heartbeat.sample_crd_active() is False


@patch("lablink_client_service.heartbeat.subprocess.run")
def test_sample_crd_active_false_on_timeout(mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired("pgrep", 2)
    assert heartbeat.sample_crd_active() is False


@patch("lablink_client_service.heartbeat.subprocess.run")
def test_sample_crd_active_false_on_missing_binary(mock_run):
    mock_run.side_effect = FileNotFoundError
    assert heartbeat.sample_crd_active() is False


@patch("lablink_client_service.heartbeat.subprocess.run")
def test_sample_docker_healthy_true(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    assert heartbeat.sample_docker_healthy() is True


@patch("lablink_client_service.heartbeat.subprocess.run")
def test_sample_docker_healthy_false_on_timeout(mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired("docker", 3)
    assert heartbeat.sample_docker_healthy() is False


@patch("lablink_client_service.heartbeat.shutil.disk_usage")
def test_sample_disk_free_pct(mock_usage):
    mock_usage.return_value = MagicMock(total=100, free=47, used=53)
    assert heartbeat.sample_disk_free_pct() == 47


@patch("lablink_client_service.heartbeat.shutil.disk_usage")
def test_sample_disk_free_pct_handles_zero_total(mock_usage):
    mock_usage.return_value = MagicMock(total=0, free=0, used=0)
    assert heartbeat.sample_disk_free_pct() == 0


@patch("lablink_client_service.heartbeat.shutil.disk_usage")
def test_sample_disk_free_pct_handles_oserror(mock_usage):
    mock_usage.side_effect = OSError("boom")
    assert heartbeat.sample_disk_free_pct() == 0


@patch("lablink_client_service.heartbeat.sample_disk_free_pct", return_value=80)
@patch("lablink_client_service.heartbeat.sample_docker_healthy", return_value=True)
@patch("lablink_client_service.heartbeat.sample_crd_active", return_value=True)
def test_build_payload_well_formed(mock_crd, mock_docker, mock_disk):
    payload = heartbeat.build_payload(vm_id="vm-1", boot_id="bid")
    assert payload["vm_id"] == "vm-1"
    assert payload["boot_id"] == "bid"
    assert payload["crd_active"] is True
    assert payload["docker_healthy"] is True
    assert payload["disk_free_pct"] == 80
    assert isinstance(payload["timestamp"], str)


@patch("lablink_client_service.heartbeat.requests.post")
def test_send_heartbeat_posts_to_correct_url(mock_post):
    mock_post.return_value = MagicMock(status_code=200, text="")
    heartbeat.send_heartbeat(
        base_url="http://alloc:5000",
        headers={"Authorization": "Bearer tok"},
        payload={"vm_id": "vm-1"},
    )
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "http://alloc:5000/api/heartbeat"
    assert kwargs["json"] == {"vm_id": "vm-1"}
    assert kwargs["headers"] == {"Authorization": "Bearer tok"}
    assert kwargs["timeout"] == heartbeat.HEARTBEAT_POST_TIMEOUT_SECONDS


@patch("lablink_client_service.heartbeat.requests.post")
def test_send_heartbeat_swallows_connection_error(mock_post, caplog):
    mock_post.side_effect = requests.exceptions.ConnectionError("unreachable")
    heartbeat.send_heartbeat(
        base_url="http://alloc",
        headers={},
        payload={"vm_id": "vm-1"},
    )


@patch("lablink_client_service.heartbeat.requests.post")
def test_send_heartbeat_swallows_timeout(mock_post):
    mock_post.side_effect = requests.exceptions.Timeout
    # Must not raise.
    heartbeat.send_heartbeat(
        base_url="http://alloc",
        headers={},
        payload={"vm_id": "vm-1"},
    )


@patch("lablink_client_service.heartbeat.requests.post")
def test_send_heartbeat_does_not_raise_on_4xx(mock_post):
    mock_post.return_value = MagicMock(status_code=404, text="not found")
    # Must not raise.
    heartbeat.send_heartbeat(
        base_url="http://alloc",
        headers={},
        payload={"vm_id": "vm-1"},
    )


@patch("lablink_client_service.heartbeat.time.sleep")
@patch(
    "lablink_client_service.heartbeat.build_payload",
    return_value={"vm_id": "vm-1"},
)
@patch("lablink_client_service.heartbeat.send_heartbeat")
@patch("lablink_client_service.heartbeat.read_boot_id", return_value="bid-1")
def test_run_heartbeat_loop_reads_boot_id_once(
    mock_boot, mock_send, mock_build, mock_sleep, vm_env
):
    # Break out of the infinite loop after the second tick.
    # build_payload is patched so the real samplers (which shell out to
    # pgrep/docker via subprocess.run) never run — subprocess uses
    # time.sleep internally on Linux, which would consume the mock's
    # side_effect list prematurely.
    mock_sleep.side_effect = [None, KeyboardInterrupt]

    with pytest.raises(KeyboardInterrupt):
        heartbeat.run_heartbeat_loop(
            allocator_url="http://alloc",
            api_token="tok",
            interval=0,
        )

    assert mock_boot.call_count == 1
    assert mock_send.call_count == 2
    assert mock_build.call_count == 2
