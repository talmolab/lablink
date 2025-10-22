import pytest
from unittest.mock import patch, MagicMock
import os
import psutil
import requests

from lablink_client_service.update_inuse_status import (
    is_process_running,
    listen_for_process,
    call_api,
)


def test_is_process_running(monkeypatch):
    # Mock psutil.process_iter to return a list of mock processes
    mock_process = MagicMock()
    mock_process.cmdline.return_value = ["python", "myproc"]
    monkeypatch.setattr("psutil.process_iter", lambda: [mock_process])
    assert is_process_running("myproc") is True


def test_is_process_running_no_process(monkeypatch):
    # Mock psutil.process_iter to return an empty list
    monkeypatch.setattr("psutil.process_iter", lambda: [])
    assert is_process_running("myproc") is False


def test_listen_for_process_triggers_callback(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _: None)
    states = [False, True]

    def fake_proc_iter():
        val = states.pop(0)
        proc = MagicMock()
        proc.cmdline.return_value = ["myproc"] if val else ["other"]
        return [proc]

    monkeypatch.setattr("psutil.process_iter", fake_proc_iter)
    called = []

    # Define a callback function that appends to the called list and raises
    # StopIteration because we want to stop listening after the first call
    def stop_callback():
        called.append(True)
        raise StopIteration

    with pytest.raises(StopIteration):
        listen_for_process("myproc", interval=0, callback_func=stop_callback)

    assert called


@patch("requests.post")
def test_call_api_success(mock_post):
    mock_post.return_value.json.return_value = {"ok": True}
    mock_post.return_value.raise_for_status = lambda: None
    call_api("myproc", "http://fake.url")
    mock_post.assert_called_once()


@patch("requests.post")
def test_call_api_timeout(mock_post, caplog):
    """Test that a requests timeout is handled gracefully."""
    mock_post.side_effect = requests.exceptions.Timeout
    call_api("myproc", "http://fake.url")
    assert "Status update timed out" in caplog.text


@patch("requests.post")
def test_call_api_request_exception(mock_post, caplog):
    """Test that a generic request exception is handled."""
    mock_post.side_effect = requests.exceptions.RequestException("Test error")
    call_api("myproc", "http://fake.url")
    assert "API call failed: Test error" in caplog.text


@patch("psutil.process_iter")
def test_is_process_running_self_skip(mock_process_iter):
    """Test that the script doesn't detect itself as the running process."""
    mock_process = MagicMock()
    mock_process.cmdline.return_value = ["python", "update_inuse_status.py", "myproc"]
    mock_process_iter.return_value = [mock_process]
    assert is_process_running("myproc") is False


@patch("psutil.process_iter")
def test_is_process_running_psutil_exception(mock_process_iter):
    """Test that psutil exceptions are handled."""
    mock_process = MagicMock()
    mock_process.cmdline.side_effect = psutil.NoSuchProcess(pid=123)
    mock_process_iter.return_value = [mock_process]
    assert is_process_running("myproc") is False


@patch("lablink_client_service.update_inuse_status.listen_for_process")
@patch.dict(os.environ, {"ALLOCATOR_URL": "https://fake-allocator.com"})
@patch("hydra.main")
def test_main_with_allocator_url(hydra_main_mock, mock_listen):
    """Test main function when ALLOCATOR_URL is set."""
    # This test is complex to set up due to Hydra. A more direct approach
    # would be to refactor the main function to be more testable.
    # For now, we are not testing the main function.
    pass
