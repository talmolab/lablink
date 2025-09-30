import pytest
from unittest.mock import patch, MagicMock

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
