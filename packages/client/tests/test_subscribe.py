import logging
from unittest.mock import patch, MagicMock
from omegaconf import OmegaConf
import pytest
from lablink_client_service.subscribe import subscribe
import requests


@pytest.fixture
def cfg():
    """Fixture to provide a mock configuration object."""
    return OmegaConf.create({"allocator": {"host": "localhost", "port": 5000}})


@pytest.fixture
def vm_env(monkeypatch):
    """Fixture to set the VM_NAME environment variable."""
    monkeypatch.setenv("VM_NAME", "vm-1")
    yield


@patch("lablink_client_service.subscribe.requests.post")
@patch("lablink_client_service.subscribe.connect_to_crd")
@patch("lablink_client_service.subscribe.set_logger")
@patch("lablink_client_service.subscribe.CloudAndConsoleLogger")
def test_run_success(
    mock_logger_cls, _set_logger, mock_connect, mock_post, cfg, vm_env
):
    """Test successful subscription."""
    # Use a real logger object so caplog can capture if you want
    mock_logger_cls.return_value = logging.getLogger("subscribe-test")

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "status": "success",
        "command": "CRD_COMMAND",
        "pin": "123456",
    }
    mock_post.return_value = resp

    subscribe(cfg)

    mock_post.assert_called_once_with(
        "http://localhost:5000/vm_startup",
        json={"hostname": "vm-1"},
        timeout=(30, 604800),
    )
    mock_connect.assert_called_once_with(pin="123456", command="CRD_COMMAND")


@patch("lablink_client_service.subscribe.requests.post")
@patch("lablink_client_service.subscribe.connect_to_crd")
@patch("lablink_client_service.subscribe.set_logger")
@patch("lablink_client_service.subscribe.CloudAndConsoleLogger")
def test_run_server_error_payload(
    mock_logger_cls, _set_logger, mock_connect, mock_post, cfg, vm_env, caplog
):
    """Test handling of server error response."""
    mock_logger_cls.return_value = logging.getLogger("subscribe-test")

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"status": "error", "message": "no available VM"}
    mock_post.return_value = resp

    caplog.set_level(logging.ERROR, logger="lablink_client_service.subscribe")
    subscribe(cfg)

    mock_connect.assert_not_called()
    # Optional: check logs
    assert "Received error response from server." in caplog.text
    assert "no available VM" in caplog.text


@patch("lablink_client_service.subscribe.time.sleep")
@patch("lablink_client_service.subscribe.requests.post")
@patch("lablink_client_service.subscribe.connect_to_crd")
@patch("lablink_client_service.subscribe.set_logger")
@patch("lablink_client_service.subscribe.CloudAndConsoleLogger")
def test_run_http_failure(
    mock_logger_cls,
    _set_logger,
    mock_connect,
    mock_post,
    mock_sleep,
    cfg,
    vm_env,
    caplog,
):
    """Test that HTTP 500 errors trigger retry logic."""
    mock_logger_cls.return_value = logging.getLogger("subscribe-test")

    # First 2 calls return 500, third call succeeds
    resp_fail = MagicMock()
    resp_fail.status_code = 500
    resp_success = MagicMock()
    resp_success.status_code = 200
    resp_success.json.return_value = {
        "status": "success",
        "command": "CRD_COMMAND",
        "pin": "123456",
    }
    mock_post.side_effect = [resp_fail, resp_fail, resp_success]

    caplog.set_level(logging.ERROR, logger="lablink_client_service.subscribe")
    subscribe(cfg)

    # Should have been called 3 times (2 failures + 1 success)
    assert mock_post.call_count == 3
    # Should have called connect_to_crd once (after success)
    mock_connect.assert_called_once_with(pin="123456", command="CRD_COMMAND")
    # Should have logged the failures
    assert "POST request failed with status code: 500" in caplog.text
    # Should have slept between retries (2 times)
    assert mock_sleep.call_count == 2


@patch("lablink_client_service.subscribe.time.sleep")
@patch("lablink_client_service.subscribe.requests.post")
@patch("lablink_client_service.subscribe.connect_to_crd")
@patch("lablink_client_service.subscribe.set_logger")
@patch("lablink_client_service.subscribe.CloudAndConsoleLogger")
def test_run_timeout_exception(
    mock_logger_cls,
    _set_logger,
    mock_connect,
    mock_post,
    mock_sleep,
    cfg,
    vm_env,
    caplog
):
    """Test that a timeout exception triggers retry logic."""
    mock_logger_cls.return_value = logging.getLogger("subscribe-test")
    mock_post.side_effect = [requests.exceptions.Timeout, MagicMock(
        status_code=200,
        json=lambda: {"status": "success", "command": "CRD_COMMAND", "pin": "123456"}
    )]

    subscribe(cfg)

    assert mock_post.call_count == 2
    mock_connect.assert_called_once()
    assert "timed out" in caplog.text
    mock_sleep.assert_called_once()
