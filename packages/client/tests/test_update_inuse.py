import pytest
from unittest.mock import patch, MagicMock
import psutil
import requests

from lablink_client_service.update_inuse_status import (
    is_process_running,
    listen_for_process,
    call_api,
    api_callback,
    main as update_main,
)
from omegaconf import OmegaConf


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


@patch("lablink_client_service.update_inuse_status.time.sleep")
@patch("requests.post")
def test_call_api_retry_logic(mock_post, mock_sleep, caplog):
    """Test the retry logic in the call_api function."""
    caplog.set_level("INFO")

    # Simulate `requests.post` failing twice then succeeding
    mock_post.side_effect = [
        requests.exceptions.RequestException("Network Error"),
        requests.exceptions.RequestException("Another Network Error"),
        MagicMock(
            status_code=200, json=lambda: {"ok": True}, raise_for_status=lambda: None
        ),
    ]

    call_api("myproc", "http://fake.url")

    # Assert that `requests.post` was called 3 times
    assert mock_post.call_count == 3

    # Assert that `time.sleep` was called twice with the correct delay
    assert mock_sleep.call_count == 2
    mock_sleep.assert_called_with(10)  # API_RETRY_DELAY is 10

    # Assert that the log messages show the retry attempts
    assert "API call failed: Network Error (Attempt 1/5). Retrying..." in caplog.text
    assert (
        "API call failed: Another Network Error (Attempt 2/5). Retrying..."
        in caplog.text
    )
    assert "Successfully updated in-use status for myproc to" in caplog.text


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


@patch("lablink_client_service.update_inuse_status.default_callback")
@patch("lablink_client_service.update_inuse_status.time.sleep", return_value=None)
@patch(
    "lablink_client_service.update_inuse_status.is_process_running",
    side_effect=[False, True, StopIteration],
)
def test_listen_for_process_default_callback(
    mock_is_process_running, mock_sleep, mock_default_callback
):
    """Test that the default callback is triggered on process state change."""
    with pytest.raises(StopIteration):
        listen_for_process("myproc", interval=0)
    mock_default_callback.assert_called_once_with("myproc")


@patch("lablink_client_service.update_inuse_status.call_api")
def test_api_callback(mock_call_api):
    """Test that the API callback calls the call_api function."""
    api_callback("myproc", "http://fake.url")
    mock_call_api.assert_called_once_with("myproc", "http://fake.url")


@patch("lablink_client_service.update_inuse_status.listen_for_process")
@patch("lablink_client_service.update_inuse_status.CloudAndConsoleLogger")
def test_update_inuse_status_main(mock_logger, mock_listen, monkeypatch):
    """Test the main function of the update_inuse_status module."""
    monkeypatch.setenv("ALLOCATOR_URL", "https://test.com")
    cfg = OmegaConf.create(
        {
            "client": {"software": "sleap"},
            "allocator": {"host": "localhost", "port": 80}
        }
    )
    update_main(cfg)

    mock_listen.assert_called_once()
    args, kwargs = mock_listen.call_args
    assert kwargs["process_name"] == "sleap"
    assert kwargs["interval"] == 20

    callback = kwargs["callback_func"]
    with patch(
        "lablink_client_service.update_inuse_status.api_callback"
        ) as mock_api_callback:
        callback()
        mock_api_callback.assert_called_once_with(
            "sleap", "https://test.com/api/update_inuse_status"
        )

