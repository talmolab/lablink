import logging
from unittest.mock import patch, MagicMock
from omegaconf import OmegaConf
import pytest
from lablink_client.subscribe import subscribe


@pytest.fixture
def cfg():
    """Fixture to provide a mock configuration object."""
    return OmegaConf.create({"allocator": {"host": "localhost", "port": 5000}})


@pytest.fixture
def vm_env(monkeypatch):
    """Fixture to set the VM_NAME environment variable."""
    monkeypatch.setenv("VM_NAME", "vm-1")
    yield


@patch("lablink_client.subscribe.requests.post")
@patch("lablink_client.subscribe.connect_to_crd")
@patch("lablink_client.subscribe.set_logger")
@patch("lablink_client.subscribe.CloudAndConsoleLogger")
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
        "http://localhost:5000/vm_startup", json={"hostname": "vm-1"}
    )
    mock_connect.assert_called_once_with(pin="123456", command="CRD_COMMAND")


@patch("lablink_client.subscribe.requests.post")
@patch("lablink_client.subscribe.connect_to_crd")
@patch("lablink_client.subscribe.set_logger")
@patch("lablink_client.subscribe.CloudAndConsoleLogger")
def test_run_server_error_payload(
    mock_logger_cls, _set_logger, mock_connect, mock_post, cfg, vm_env, caplog
):
    """Test handling of server error response."""
    mock_logger_cls.return_value = logging.getLogger("subscribe-test")

    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"status": "error", "message": "no available VM"}
    mock_post.return_value = resp

    caplog.set_level(logging.ERROR, logger="lablink_client.subscribe")
    subscribe(cfg)

    mock_connect.assert_not_called()
    # Optional: check logs
    assert "Received error response from server." in caplog.text
    assert "no available VM" in caplog.text


@patch("lablink_client.subscribe.requests.post")
@patch("lablink_client.subscribe.connect_to_crd")
@patch("lablink_client.subscribe.set_logger")
@patch("lablink_client.subscribe.CloudAndConsoleLogger")
def test_run_http_failure(
    mock_logger_cls, _set_logger, mock_connect, mock_post, cfg, vm_env, caplog
):
    mock_logger_cls.return_value = logging.getLogger("subscribe-test")

    resp = MagicMock()
    resp.status_code = 500
    mock_post.return_value = resp

    caplog.set_level(logging.ERROR, logger="lablink_client.subscribe")
    subscribe(cfg)

    mock_connect.assert_not_called()
    assert "POST request failed with status code: 500" in caplog.text
