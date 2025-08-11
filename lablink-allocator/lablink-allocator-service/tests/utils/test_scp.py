import os
import json
import builtins
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import pytest

from utils.scp import (
    get_instance_ips,
    get_ssh_private_key,
    find_slp_files_in_container,
    extract_slp_from_docker,
    has_slp_files,
    rsync_slp_files_to_allocator,
)


@patch("subprocess.run")
def test_get_instance_ips_success(mock_run):
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
    assert str(kwargs["cwd"]).endswith("/fake/terraform/dir")
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["check"] is True


@patch("subprocess.run")
def test_get_instance_ips_nonzero_returncode(mock_run):
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
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="not-json", stderr=""
    )
    with pytest.raises(RuntimeError, match="Error decoding JSON output"):
        get_instance_ips("/fake/terraform/dir")


@patch("subprocess.run")
def test_get_instance_ips_not_a_list(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps({"ip": "1.2.3.4"}), stderr=""
    )
    with pytest.raises(ValueError, match="Expected output to be a list"):
        get_instance_ips("/fake/terraform/dir")


@patch("os.chmod")
@patch("builtins.open", new_callable=mock_open)
@patch("subprocess.run")
def test_get_ssh_private_key_success(mock_run, mock_file, mock_chmod, tmp_path):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="PRIVATE_KEY_CONTENT", stderr=""
    )
    key_path = get_ssh_private_key("/fake/terraform/dir")
    assert key_path == "/tmp/lablink_key.pem"
    mock_file.assert_called_once_with("/tmp/lablink_key.pem", "w")
    mock_chmod.assert_called_once_with("/tmp/lablink_key.pem", 0o400)


@patch("subprocess.run")
def test_get_ssh_private_key_failure(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["terraform", "output", "-raw", "lablink_private_key_pem"],
        returncode=1,
        stdout="",
        stderr="error message",
    )
    with pytest.raises(RuntimeError, match="Error running terraform output"):
        get_ssh_private_key("/fake/terraform/dir")


@patch("subprocess.run")
def test_find_slp_files_success(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="/path/file1.slp\n/path/file2.slp\n", stderr=""
    )
    files = find_slp_files_in_container("1.2.3.4", "/fake/key.pem")
    assert files == ["/path/file1.slp", "/path/file2.slp"]


@patch("subprocess.run")
def test_find_slp_files_empty(mock_run, caplog):
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1, cmd=["ssh"], stderr="error msg"
    )
    with caplog.at_level("ERROR"):
        result = find_slp_files_in_container("1.2.3.4", "/fake/key.pem")
    assert result == []
    assert any(
        "Error finding .slp files in container on 1.2.3.4" in r.message
        for r in caplog.records
    )


@patch("subprocess.run")
def test_extract_slp_from_docker_success(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="Extracted SLP content",
        stderr="",
    )
    extract_slp_from_docker("1.2.3.4", "/fake/key.pem", ["/path/file1.slp"])
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_extract_slp_from_docker_failure(mock_run, caplog):
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd=["ssh"],
        stderr="error message",
    )
    with caplog.at_level("ERROR"):
        extract_slp_from_docker("1.2.3.4", "/fake/key.pem", ["/path/file1.slp"])
    mock_run.assert_called_once()
    assert any(
        "Failed to copy /path/file1.slp from container on 1.2.3.4" in r.message
        for r in caplog.records
    )


@patch("subprocess.run")
def test_has_slp_files_found(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="exists",
        stderr="",
    )
    result = has_slp_files("1.2.3.4", "/fake/key.pem")
    assert result is True


@patch("subprocess.run")
def test_has_slp_files_missing(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout="missing",
        stderr="",
    )
    result = has_slp_files("1.2.3.4", "/fake/key.pem")
    assert result is False


@patch("utils.scp.has_slp_files", return_value=True)
@patch("subprocess.run")
def test_rsync_slp_files_to_allocator_test_success(mock_run, mock_has_slp_files):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="", stderr=""
    )
    key_path = "/fake/key.pem"
    ip = "1.2.3.4"
    local_dir = "/tmp/slp_files"

    rsync_slp_files_to_allocator(ip=ip, key_path=key_path, local_dir=local_dir)
    assert mock_has_slp_files.call_count == 1
    args, kwargs = mock_run.call_args
    assert args[0] == [
        "rsync",
        "-avz",
        "--include",
        "**/",
        "--include",
        "**.slp",
        "--exclude",
        "*",
        "-e",
        f"ssh -o StrictHostKeyChecking=no -i {key_path}",
        f"ubuntu@{ip}:/home/ubuntu/slp_files/",
        f"{local_dir}/",
    ]


@patch("utils.scp.has_slp_files", return_value=False)
@patch("subprocess.run")
def test_rsync_slp_files_to_allocator_test_skip(mock_run, mock_has_slp_files):
    rsync_slp_files_to_allocator(
        ip="1.2.3.4", key_path="/fake/key.pem", local_dir="/tmp/slp_files"
    )
    mock_run.assert_not_called()


@patch("utils.scp.has_slp_files", return_value=True)
@patch("subprocess.run")
def test_rsync_slp_files_to_allocator_test_error(mock_run, mock_has_slp_files, caplog):
    mock_run.side_effect = subprocess.CalledProcessError(
        returncode=1,
        cmd=["rsync"],
        stderr="error message",
    )
    with caplog.at_level("ERROR"):
        with pytest.raises(subprocess.CalledProcessError):
            rsync_slp_files_to_allocator(
                ip="1.2.3.4", key_path="/fake/key.pem", local_dir="/tmp/slp_files"
            )
    mock_run.assert_called_once()
    assert any(
        "Error copying .slp files from 1.2.3.4" in r.message for r in caplog.records
    )
    assert any("Rsync stderr:\nerror message" in r.message for r in caplog.records)
