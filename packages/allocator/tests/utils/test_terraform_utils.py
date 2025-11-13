import json
import subprocess
from unittest.mock import patch, mock_open
import pytest

from lablink_allocator_service.utils.terraform_utils import (
    get_instance_ips,
    get_ssh_private_key,
    get_instance_names,
    get_instance_ids,
    get_instance_timings,
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
    mock_run.side_effect = subprocess.CalledProcessError(
        1, "terraform", stderr="error message"
    )
    with pytest.raises(RuntimeError, match="Error running terraform output: error message"):
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
    with pytest.raises(ValueError, match="Expected output to be a list of IP addresses"):
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
    mock_run.side_effect = subprocess.CalledProcessError(
        1, "terraform", stderr="error message"
    )
    with pytest.raises(RuntimeError, match="Error running terraform output: error message"):
        get_ssh_private_key("/fake/terraform/dir")


@patch("subprocess.run")
def test_get_instance_ids_success(mock_run):
    """Test getting instance IDs successfully."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=["terraform", "output", "-json", "vm_instance_ids"],
        returncode=0,
        stdout=json.dumps(["i-12345", "i-67890"]),
        stderr="",
    )
    ids = get_instance_ids("/fake/terraform/dir")
    assert ids == ["i-12345", "i-67890"]
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_get_instance_names_success(mock_run):
    """Test getting instance names successfully."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=["terraform", "output", "-json", "vm_instance_names"],
        returncode=0,
        stdout=json.dumps(["instance-1", "instance-2"]),
        stderr="",
    )
    names = get_instance_names("/fake/terraform/dir")
    assert names == ["instance-1", "instance-2"]
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_get_instance_ids_failure(mock_run):
    """Test handling failure when getting instance IDs."""
    mock_run.side_effect = subprocess.CalledProcessError(1, "cmd", stderr="error")
    with pytest.raises(RuntimeError, match="Error running terraform output: error"):
        get_instance_ids("/fake/terraform/dir")


@patch("subprocess.run")
def test_get_instance_names_failure(mock_run):
    """Test handling failure when getting instance names."""
    mock_run.side_effect = subprocess.CalledProcessError(1, "cmd", stderr="error")
    with pytest.raises(RuntimeError, match="Error running terraform output: error"):
        get_instance_names("/fake/terraform/dir")


@patch("subprocess.run")
def test_get_instance_ids_invalid_json(mock_run):
    """Test handling invalid JSON output when getting instance IDs."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="not-json", stderr=""
    )
    with pytest.raises(RuntimeError, match="Error decoding JSON output"):
        get_instance_ids("/fake/terraform/dir")


@patch("subprocess.run")
def test_get_instance_names_invalid_json(mock_run):
    """Test handling invalid JSON output when getting instance names."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="not-json", stderr=""
    )
    with pytest.raises(RuntimeError, match="Error decoding JSON output"):
        get_instance_names("/fake/terraform/dir")


@patch("subprocess.run")
def test_get_instance_ids_not_a_list(mock_run):
    """Test handling non-list output when getting instance IDs."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps({"id": "i-12345"}), stderr=""
    )
    with pytest.raises(ValueError, match="Expected output to be a list of instance IDs"):
        get_instance_ids("/fake/terraform/dir")


@patch("subprocess.run")
def test_get_instance_names_not_a_list(mock_run):
    """Test handling non-list output when getting instance names."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps({"name": "instance-1"}),
        stderr="",
    )
    with pytest.raises(ValueError, match="Expected output to be a list of instance names"):
        get_instance_names("/fake/terraform/dir")


@patch("subprocess.run")
def test_get_instance_timings_not_a_dict(mock_run):
    """Test handling non-dict output when getting instance timings."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps(["timing-1", "timing-2"]),
        stderr="",
    )
    with pytest.raises(ValueError, match="Expected output to be a dictionary of launch times"):
        get_instance_timings("/fake/terraform/dir")


@patch("subprocess.run")
def test_get_instance_timings_failure(mock_run):
    """Test handling failure when getting instance timings."""
    mock_run.side_effect = subprocess.CalledProcessError(1, "cmd", stderr="error")
    with pytest.raises(RuntimeError, match="Error running terraform output: error"):
        get_instance_timings("/fake/terraform/dir")


@patch("subprocess.run")
def test_get_instance_timings_invalid_json(mock_run):
    """Test handling invalid JSON output when getting instance timings."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="not-json", stderr=""
    )
    with pytest.raises(RuntimeError, match="Error decoding JSON output"):
        get_instance_timings("/fake/terraform/dir")


@patch("subprocess.run")
def test_get_instance_timings_success(mock_run):
    """Test getting instance timings successfully."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=["terraform", "output", "-json", "instance_terraform_apply_times"],
        returncode=0,
        stdout=json.dumps({"instance-1": "time-1", "instance-2": "time-2"}),
        stderr="",
    )
    timings = get_instance_timings("/fake/terraform/dir")
    assert timings == {"instance-1": "time-1", "instance-2": "time-2"}
    mock_run.assert_called_once()
