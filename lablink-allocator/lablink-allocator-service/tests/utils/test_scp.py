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
        args=[],
        returncode=0,
        stdout=json.dumps(["1.2.3.4", "5.6.7.8"]),
        stderr="",
    )
    ips = get_instance_ips("/fake/terraform/dir")
    assert ips == ["1.2.3.4", "5.6.7.8"]
    mock_run.assert_called_once()


@patch("subprocess.run")
def test_get_instance_ips_nonzero_returncode(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout="",
        stderr="error msg",
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
        args=[], returncode=1, stdout="", stderr="error msg"
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
def test_find_slp_files_empty(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="error msg"
    )
    result = find_slp_files_in_container("1.2.3.4", "/fake/key.pem")
    assert result == []


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
def test_extract_slp_from_docker_failure(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=1,
        stdout="",
        stderr="error msg",
    )
    extract_slp_from_docker("1.2.3.4", "/fake/key.pem", ["/path/file1.slp"])
    mock_run.assert_called_once()


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
