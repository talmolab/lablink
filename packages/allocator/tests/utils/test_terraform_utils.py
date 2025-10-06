import json
import subprocess
from unittest.mock import patch, mock_open
import pytest

from lablink_allocator.utils.terraform_utils import (
    get_instance_ips,
    get_ssh_private_key,
)


@patch("subprocess.run")
def test_get_instance_ips_success(mock_run):
    """Test getting instance IPs successfully."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=["terraform", "output", "-json", "vm_public_ips"],
        returncode=0,
        stdout=json.dumps(["1.2.3.4", "5.6.7.8"]),
        stderr="",
    )
    ips = get_instance_ips("/fake/terraform/dir")
    assert ips == ["1.2.3.4", "5.6.7.8"]
    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args == (["terraform", "output", "-json", "vm_public_ips"],)
    # Check path ends with directory name (works on Windows and Unix)
    assert str(kwargs["cwd"]).replace("\\", "/").endswith("/fake/terraform/dir")
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["check"] is True


@patch("subprocess.run")
def test_get_instance_ips_nonzero_returncode(mock_run):
    """Test handling non-zero return code when getting instance IPs."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=["terraform", "output", "-json", "vm_public_ips"],
        returncode=1,
        stdout="",
        stderr="error message",
    )
    with pytest.raises(RuntimeError, match="Error running terraform output"):
        get_instance_ips("/fake/terraform/dir")


@patch("subprocess.run")
def test_get_instance_ips_invalid_json(mock_run):
    """Test handling invalid JSON output when getting instance IPs."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="not-json", stderr=""
    )
    with pytest.raises(RuntimeError, match="Error decoding JSON output"):
        get_instance_ips("/fake/terraform/dir")


@patch("subprocess.run")
def test_get_instance_ips_not_a_list(mock_run):
    """Test handling unexpected output format when getting instance IPs."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps({"ip": "1.2.3.4"}), stderr=""
    )
    with pytest.raises(ValueError, match="Expected output to be a list"):
        get_instance_ips("/fake/terraform/dir")


@patch("os.chmod")
@patch("builtins.open", new_callable=mock_open)
@patch("subprocess.run")
def test_get_ssh_private_key_success(mock_run, mock_file, mock_chmod, tmp_path):
    """Test getting SSH private key successfully."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="PRIVATE_KEY_CONTENT", stderr=""
    )
    key_path = get_ssh_private_key("/fake/terraform/dir")
    assert key_path == "/tmp/lablink_key.pem"
    mock_file.assert_called_once_with("/tmp/lablink_key.pem", "w")
    mock_chmod.assert_called_once_with("/tmp/lablink_key.pem", 0o400)


@patch("subprocess.run")
def test_get_ssh_private_key_failure(mock_run):
    """Test handling failure when getting SSH private key."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=["terraform", "output", "-raw", "lablink_private_key_pem"],
        returncode=1,
        stdout="",
        stderr="error message",
    )
    with pytest.raises(RuntimeError, match="Error running terraform output"):
        get_ssh_private_key("/fake/terraform/dir")
