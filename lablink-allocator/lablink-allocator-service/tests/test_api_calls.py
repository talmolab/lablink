from unittest.mock import patch, MagicMock
from pathlib import Path
import io
import zipfile
import subprocess


VM_STARTUP_ENDPOINT = "/vm_startup"
UNASSIGNED_VMS_COUNT_ENDPOINT = "/api/unassigned_vms_count"
UPDATE_INUSE_STATUS_ENDPOINT = "/api/update_inuse_status"
UPDATE_GPU_HEALTH_ENDPOINT = "/api/gpu_health"
REQUEST_VM_ENDPOINT = "/api/request_vm"
SCP_ENDPOINT = "/api/scp-client"
VM_STATUS_UPDATE_ENDPOINT = "/api/vm-status"
VM_LOGS_ENDPOINT = "/api/vm-logs"


def test_vm_startup_success(client, monkeypatch):
    """Test VM startup success with valid hostname."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.insert_vm.return_value = None
    fake_db.listen_for_notifications.return_value = {
        "status": "success",
        "pin": "123456",
        "command": "sample_command_payload",
    }

    # Patch globals
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    data = {"hostname": "test-vm-dev-1"}
    resp = client.post(VM_STARTUP_ENDPOINT, json=data)

    # Assert the response
    expected_response = {
        "status": "success",
        "pin": "123456",
        "command": "sample_command_payload",
    }
    assert resp.status_code == 200
    assert resp.get_json() == expected_response
    fake_db.listen_for_notifications.assert_called_once_with(
        channel="vm_updates", target_hostname="test-vm-dev-1"
    )


def test_vm_startup_failure(client, monkeypatch):
    """Test VM startup failure due to missing hostname."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.insert_vm.return_value = None
    fake_db.listen_for_notifications.return_value = {
        "status": "failure",
        "error": "VM startup failed",
    }

    # Patch globals
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    data = {"hostname": ""}
    resp = client.post(VM_STARTUP_ENDPOINT, json=data)

    # Assert the response
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "Hostname is required."}
    fake_db.insert_vm.assert_not_called()
    fake_db.listen_for_notifications.assert_not_called()


def test_unassigned_vms_count(client, monkeypatch):
    """Test the /api/unassigned_vms_count endpoint."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_unassigned_vms.return_value = [
        {
            "hostname": "test-vm-dev-1",
            "crdcommand": "",
            "pin": "",
            "useremail": "",
            "inuse": False,
            "healthy": "Healthy",
        },
        {
            "hostname": "test-vm-dev-2",
            "crdcommand": "",
            "pin": "",
            "useremail": "",
            "inuse": False,
            "healthy": "Healthy",
        },
    ]

    # Patch globals
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    resp = client.get(UNASSIGNED_VMS_COUNT_ENDPOINT)

    # Assert the response
    assert resp.status_code == 200
    assert resp.get_json() == {"count": 2}
    fake_db.get_unassigned_vms.assert_called_once()


def test_update_inuse_status_success(client, monkeypatch):
    """Test the /api/update_inuse_status endpoint."""
    # Mock the database
    fake_db = MagicMock()

    # Patch globals
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    data = {"hostname": "test-vm-dev-1", "status": True}
    resp = client.post(UPDATE_INUSE_STATUS_ENDPOINT, json=data)

    # Assert the response
    assert resp.status_code == 200
    assert resp.get_json() == {"message": "In-use status updated successfully."}
    fake_db.update_vm_in_use.assert_called_once_with(
        hostname="test-vm-dev-1", in_use=True
    )


def test_update_inuse_status_missing_hostname(client, monkeypatch):
    """Test the /api/update_inuse_status endpoint with missing hostname."""
    # Mock the database
    fake_db = MagicMock()

    # Patch globals
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    data = {"status": True}
    resp = client.post(UPDATE_INUSE_STATUS_ENDPOINT, json=data)

    # Assert the response
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "Hostname is required."}
    fake_db.update_vm_in_use.assert_not_called()


def test_update_inuse_status_failure(client, monkeypatch):
    """Test the /api/update_inuse_status endpoint with database internal failure."""
    # Mock the database
    fake_db = MagicMock()

    # Failure while update inuse status
    fake_db.update_vm_in_use.side_effect = Exception("Database internal error")

    # Patch the database
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    data = {"hostname": "test-vm-dev-1", "status": True}
    resp = client.post(UPDATE_INUSE_STATUS_ENDPOINT, json=data)

    # Assert the response
    assert resp.status_code == 500
    assert resp.get_json() == {"error": "Failed to update in-use status."}
    fake_db.update_vm_in_use.assert_called_once_with(
        hostname="test-vm-dev-1", in_use=True
    )


def test_update_gpu_health_success(client, monkeypatch):
    """Test the /api/gpu_health endpoint."""
    # Mock the database
    fake_db = MagicMock()

    # Patch globals
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    data = {"hostname": "test-vm-dev-1", "gpu_status": "Healthy"}
    resp = client.post(UPDATE_GPU_HEALTH_ENDPOINT, json=data)

    # Assert the response
    assert resp.status_code == 200
    assert resp.get_json() == {"message": "GPU health status updated successfully."}
    fake_db.update_health.assert_called_once_with(
        hostname="test-vm-dev-1", healthy="Healthy"
    )


def test_update_gpu_health_missing_hostname(client, monkeypatch):
    """Test the /api/gpu_health endpoint with missing hostname."""
    # Mock the database
    fake_db = MagicMock()

    # Patch globals
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    data = {}
    resp = client.post(UPDATE_GPU_HEALTH_ENDPOINT, json=data)

    # Assert the response
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "GPU status and hostname are required."}
    fake_db.update_health.assert_not_called()


def test_update_gpu_health_failure(client, monkeypatch):
    """Test the /api/gpu_health endpoint with database internal failure."""
    # Mock the database
    fake_db = MagicMock()

    # Failure while update gpu health
    fake_db.update_health.side_effect = Exception("Database internal error")

    # Patch the database
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    data = {"hostname": "test-vm-dev-1", "gpu_status": "Healthy"}
    resp = client.post(UPDATE_GPU_HEALTH_ENDPOINT, json=data)

    # Assert the response
    assert resp.status_code == 500
    assert resp.get_json() == {"error": "Failed to update GPU health status."}
    fake_db.update_health.assert_called_once_with(
        hostname="test-vm-dev-1", healthy="Healthy"
    )


def test_update_gpu_health_missing_hostname(client, monkeypatch):
    """Test the /api/gpu_health endpoint with missing hostname."""
    # Mock the database
    fake_db = MagicMock()

    # Patch globals
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    data = {"gpu_status": "Healthy"}
    resp = client.post(UPDATE_GPU_HEALTH_ENDPOINT, json=data)

    # Assert the response
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "GPU status and hostname are required."}
    fake_db.update_health.assert_not_called()


def test_request_vm_success(client, monkeypatch):
    """Test the /api/request_vm endpoint with valid data."""
    # Mock the database
    fake_db = MagicMock()

    fake_db.get_unassigned_vms.return_value = [
        {
            "hostname": "test-vm-dev-1",
            "crdcommand": "",
            "pin": "",
            "useremail": "",
            "inuse": False,
            "healthy": "Healthy",
        },
        {
            "hostname": "test-vm-dev-2",
            "crdcommand": "",
            "pin": "",
            "useremail": "",
            "inuse": False,
            "healthy": "Healthy",
        },
    ]
    fake_db.get_vm_details.return_value = [
        "test-vm-dev-1",
        "DISPLAY=:0 --code=123",
        "user@example.com",
    ]

    # Patch the database
    monkeypatch.setattr("main.database", fake_db, raising=False)
    monkeypatch.setattr("main.check_crd_input", lambda crd_command: True, raising=False)

    # Call the API
    data = {"email": "user@example.com", "crd_command": "DISPLAY=:0 --code=123"}
    resp = client.post(REQUEST_VM_ENDPOINT, data=data)

    # Assert response
    assert resp.status_code == 200
    assert b"Success" in resp.data
    assert b"test-vm-dev-1" in resp.data
    fake_db.get_unassigned_vms.assert_called_once()
    fake_db.get_vm_details.assert_called_once_with(email="user@example.com")
    fake_db.assign_vm.assert_called_once_with(
        email="user@example.com", crd_command="DISPLAY=:0 --code=123", pin="123456"
    )


def test_request_vm_missing(client, monkeypatch):
    """Test the /api/request_vm endpoint with missing data."""
    # Mock the database
    fake_db = MagicMock()

    # Patch the database
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API with missing data
    data = {}
    resp = client.post(REQUEST_VM_ENDPOINT, data=data)

    # Assert response
    assert resp.status_code == 200
    assert b"Email and CRD command are required." in resp.data


def test_request_vm_invalid_crd(client, monkeypatch):
    """Test the /api/request_vm endpoint with invalid CRD command."""
    # Mock the database
    fake_db = MagicMock()

    # Patch the database
    monkeypatch.setattr("main.database", fake_db, raising=False)
    monkeypatch.setattr(
        "main.check_crd_input", lambda crd_command: False, raising=False
    )

    # Call the API with invalid CRD command
    data = {"email": "user@example.com", "crd_command": "<invalid_crd_command>"}
    resp = client.post(REQUEST_VM_ENDPOINT, data=data)

    # Assert response
    assert resp.status_code == 200
    assert b"Invalid" in resp.data
    fake_db.get_unassigned_vms.assert_not_called()
    fake_db.get_vm_details.assert_not_called()
    fake_db.assign_vm.assert_not_called()


def test_request_vm_no_vm_available(client, monkeypatch):
    """Test the /api/request_vm endpoint when no VMs are available."""
    # Mock the database
    fake_db = MagicMock()

    fake_db.get_unassigned_vms.return_value = []

    # Patch the database
    monkeypatch.setattr("main.database", fake_db, raising=False)
    monkeypatch.setattr("main.check_crd_input", lambda crd_command: True, raising=False)

    # Call the API
    data = {"email": "user@example.com", "crd_command": "DISPLAY=:0 --code=123"}
    resp = client.post(REQUEST_VM_ENDPOINT, data=data)

    # Assert response
    assert resp.status_code == 200
    assert b"No available VMs." in resp.data
    fake_db.get_unassigned_vms.assert_called_once()
    fake_db.get_vm_details.assert_not_called()
    fake_db.assign_vm.assert_not_called()


def test_request_vm_database_internal_failure(client, monkeypatch):
    """Test the /api/request_vm endpoint when the database fails."""
    # Mock the database
    fake_db = MagicMock()

    fake_db.get_unassigned_vms.side_effect = Exception("Database error")

    # Patch the database and functions
    monkeypatch.setattr("main.database", fake_db, raising=False)
    monkeypatch.setattr("main.check_crd_input", lambda crd_command: True, raising=False)

    # Call the API
    data = {"email": "user@example.com", "crd_command": "DISPLAY=:0 --code=123"}
    resp = client.post(REQUEST_VM_ENDPOINT, data=data)

    # Assert response
    assert resp.status_code == 200
    assert b"An unexpected error" in resp.data
    fake_db.get_unassigned_vms.assert_called_once()
    fake_db.get_vm_details.assert_not_called()
    fake_db.assign_vm.assert_not_called()


def test_scp_client_404_when_no_rows(client, admin_headers, monkeypatch):
    """Test the /api/scp-client endpoint when no VMs are found."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_row_count.return_value = 0
    monkeypatch.setattr("main.database", fake_db, raising=False)

    resp = client.get(SCP_ENDPOINT, headers=admin_headers)
    assert resp.status_code == 404
    assert resp.is_json
    assert resp.get_json()["error"].startswith("No VMs found")


def test_scp_success(client, admin_headers, monkeypatch):
    """Test the /api/scp-client endpoint for successful SCP."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_row_count.return_value = 1

    # Patch the database and util functions
    monkeypatch.setattr("main.database", fake_db, raising=False)
    monkeypatch.setattr("main.get_instance_ips", lambda terraform_dir: ["10.0.0.1"])
    monkeypatch.setattr(
        "main.get_ssh_private_key", lambda terraform_dir: "/tmp/key.pem"
    )
    monkeypatch.setattr(
        "main.find_slp_files_in_container",
        lambda ip, key_path: ["/remote/path/sample.slp"],
    )
    monkeypatch.setattr("main.extract_slp_from_docker", lambda **kwargs: None)

    # Dummy function for rsync
    def fake_rsync(ip, key_path, local_dir):
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        (Path(local_dir) / "sample.slp").write_text("dummy")

    monkeypatch.setattr("main.rsync_slp_files_to_allocator", fake_rsync)

    # Call the API
    resp = client.get(SCP_ENDPOINT, headers=admin_headers)
    assert resp.status_code == 200
    # Content-Disposition should look like a file download
    disp = resp.headers.get("Content-Disposition", "")
    assert "attachment" in disp and "lablink_data" in disp

    # The body is the zip file bytes; inspect without touching disk
    zf = zipfile.ZipFile(io.BytesIO(resp.data))
    names = zf.namelist()
    # The arcname is relative to temp_dir: e.g., vm_1/sample.slp
    assert any(n.endswith("vm_1/sample.slp") for n in names), names
    # Optional: verify file content
    with zf.open([n for n in names if n.endswith("vm_1/sample.slp")][0]) as f:
        assert f.read() == b"dummy"


def test_scp_multiple_vms_success_calls_per_ip(client, admin_headers, monkeypatch):
    # DB has rows
    fake_db = MagicMock(get_row_count=MagicMock(return_value=2))
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Two IPs
    monkeypatch.setattr(
        "main.get_instance_ips", lambda terraform_dir: ["10.0.0.1", "10.0.0.2"]
    )
    monkeypatch.setattr(
        "main.get_ssh_private_key", lambda terraform_dir: "/tmp/key.pem"
    )

    # Create MagicMocks for each function
    find_slp = MagicMock(return_value=["/remote/path/sample.slp"])
    extract = MagicMock()
    rsync = MagicMock(
        side_effect=lambda ip, key_path, local_dir: (
            Path(local_dir).mkdir(parents=True, exist_ok=True),
            (Path(local_dir) / "sample.slp").write_text("dummy"),
        )
    )

    # Use MagicMocks so we can assert call counts/args
    monkeypatch.setattr("main.find_slp_files_in_container", find_slp, raising=False)
    monkeypatch.setattr("main.extract_slp_from_docker", extract, raising=False)
    monkeypatch.setattr("main.rsync_slp_files_to_allocator", rsync, raising=False)

    resp = client.get(SCP_ENDPOINT, headers=admin_headers)
    assert resp.status_code == 200

    # Verify we zipped both vm_1 and vm_2 data
    zf = zipfile.ZipFile(io.BytesIO(resp.data))
    names = set(zf.namelist())
    assert any(n.endswith("vm_1/sample.slp") for n in names)
    assert any(n.endswith("vm_2/sample.slp") for n in names)

    # Check call counts
    assert find_slp.call_count == 2
    assert extract.call_count == 2
    assert rsync.call_count == 2

    # Args contain both IPs
    ips_seen = {call.kwargs.get("ip") or call.args[0] for call in find_slp.mock_calls}
    assert ips_seen == {"10.0.0.1", "10.0.0.2"}

    # rsync local_dir should end with vm_1 and vm_2 respectively
    local_dirs = [(c.kwargs.get("local_dir") or c.args[2]) for c in rsync.mock_calls]
    assert local_dirs[0].endswith("vm_1")
    assert local_dirs[1].endswith("vm_2")


def test_scp_multiple_vms_skips_when_no_slp(client, admin_headers, monkeypatch):
    """Test the /api/scp-client endpoint when some VMs have no SLP files."""
    # Mock the database
    fake_db = MagicMock(get_row_count=MagicMock(return_value=2))
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Mock the utility functions
    monkeypatch.setattr(
        "main.get_instance_ips", lambda terraform_dir: ["10.0.0.1", "10.0.0.2"]
    )
    monkeypatch.setattr(
        "main.get_ssh_private_key", lambda terraform_dir: "/tmp/key.pem"
    )

    # First VM has .slp files; second has none
    def find_side_effect(ip, key_path):
        return ["/remote/sample.slp"] if ip == "10.0.0.1" else []

    # Mock the file operations
    find_slp = MagicMock(side_effect=find_side_effect)
    extract = MagicMock()
    rsync = MagicMock(
        side_effect=lambda ip, key_path, local_dir: (
            Path(local_dir).mkdir(parents=True, exist_ok=True),
            (Path(local_dir) / "sample.slp").write_text("dummy"),
        )
    )
    monkeypatch.setattr("main.find_slp_files_in_container", find_slp, raising=False)
    monkeypatch.setattr("main.extract_slp_from_docker", extract, raising=False)
    monkeypatch.setattr("main.rsync_slp_files_to_allocator", rsync, raising=False)

    # Call the API
    resp = client.get(SCP_ENDPOINT, headers=admin_headers)
    assert resp.status_code == 200

    # Only vm_1 present in zip
    zf = zipfile.ZipFile(io.BytesIO(resp.data))
    names = set(zf.namelist())
    assert any(n.endswith("vm_1/sample.slp") for n in names)
    assert not any(n.endswith("vm_2/sample.slp") for n in names)

    # Find called for both; extract/rsync only for the one with files
    assert find_slp.call_count == 2
    assert extract.call_count == 1
    assert rsync.call_count == 1

    # Check we extracted/rsynced only the first IP
    called_ips_extract = {c.kwargs.get("ip") or c.args[0] for c in extract.mock_calls}
    called_ips_rsync = {c.kwargs.get("ip") or c.args[0] for c in rsync.mock_calls}
    assert called_ips_extract == {"10.0.0.1"}
    assert called_ips_rsync == {"10.0.0.1"}


def test_scp_no_vms_failure(client, admin_headers, monkeypatch):
    """Test the /api/scp-client endpoint when no VMs are found."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_row_count.return_value = 0

    # Patch the database and util functions
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    resp = client.get(SCP_ENDPOINT, headers=admin_headers)
    assert resp.status_code == 404
    assert resp.is_json
    assert resp.get_json() == {"error": "No VMs found in the database."}


def test_scp_no_slp_files_failure(client, admin_headers, monkeypatch):
    """Test the /api/scp-client endpoint when no SLP files are found."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_row_count.return_value = 1

    # Patch the database and util functions
    monkeypatch.setattr("main.database", fake_db, raising=False)
    monkeypatch.setattr("main.get_instance_ips", lambda terraform_dir: ["10.0.0.1"])
    monkeypatch.setattr(
        "main.get_ssh_private_key", lambda terraform_dir: "/tmp/key.pem"
    )
    monkeypatch.setattr("main.find_slp_files_in_container", lambda ip, key_path: [])
    monkeypatch.setattr("main.extract_slp_from_docker", lambda **kwargs: None)

    # Call the API
    resp = client.get(SCP_ENDPOINT, headers=admin_headers)
    assert resp.status_code == 404
    assert resp.is_json
    assert resp.get_json() == {"error": "No .slp files found in any VMs."}


def test_scp_internal_failure(client, admin_headers, monkeypatch, tmp_path):
    # DB has rows
    fake_db = MagicMock()
    fake_db.get_row_count.return_value = 1
    monkeypatch.setattr("main.database", fake_db, raising=False)

    monkeypatch.chdir(tmp_path)
    Path("terraform").mkdir(exist_ok=True)

    monkeypatch.setattr("main.get_instance_ips", lambda terraform_dir: ["10.0.0.1"])
    monkeypatch.setattr(
        "main.get_ssh_private_key", lambda terraform_dir: "/tmp/key.pem"
    )
    monkeypatch.setattr(
        "main.find_slp_files_in_container", lambda ip, key_path: ["/remote/sample.slp"]
    )

    # Make one of the steps raise a CalledProcessError to trigger 500 path
    def explode(**kwargs):
        raise subprocess.CalledProcessError(1, ["rsync"], "boom")

    monkeypatch.setattr("main.extract_slp_from_docker", explode)

    resp = client.get(SCP_ENDPOINT, headers=admin_headers)
    assert resp.status_code == 500
    assert resp.is_json
    assert "downloading data from VMs" in resp.get_json()["error"]


def test_update_vm_status_success(client, monkeypatch):
    """Test successful VM status update."""
    # Mock the database
    fake_db = MagicMock()
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    resp = client.post(
        VM_STATUS_UPDATE_ENDPOINT,
        json={"hostname": "lablink-vm-test-1", "status": "running"},
    )

    assert resp.status_code == 200
    assert resp.is_json
    assert resp.get_json() == {"message": "VM status updated successfully."}
    fake_db.update_vm_status.assert_called_once_with(
        hostname="lablink-vm-test-1", status="running"
    )


def test_update_vm_status_missing_fields(client, monkeypatch):
    """Test VM status update with missing fields."""
    # Mock the database
    fake_db = MagicMock()
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API without the hostname
    resp = client.post(
        VM_STATUS_UPDATE_ENDPOINT,
        json={"status": "running"},
    )

    assert resp.status_code == 400
    assert resp.is_json
    assert resp.get_json() == {"error": "Hostname and status are required."}
    fake_db.update_vm_status.assert_not_called()


def test_update_vm_status_internal_failure(client, monkeypatch):
    """Test VM status update with internal failure."""
    # Mock the database
    fake_db = MagicMock()
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Simulate an internal error
    fake_db.update_vm_status.side_effect = Exception("Internal error")

    # Call the API with valid data
    resp = client.post(
        VM_STATUS_UPDATE_ENDPOINT,
        json={"hostname": "lablink-vm-test-1", "status": "running"},
    )

    assert resp.status_code == 500
    assert resp.is_json
    assert resp.get_json() == {"error": "Failed to update VM status."}


def test_get_vm_status_by_hostname_success(client, monkeypatch):
    """Test getting VM status by hostname."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_status_by_hostname.return_value = "running"
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    resp = client.get("/api/vm-status/lablink-vm-test-1")

    assert resp.status_code == 200
    assert resp.is_json
    assert resp.get_json() == {
        "hostname": "lablink-vm-test-1",
        "status": "running",
    }
    fake_db.get_status_by_hostname.assert_called_once_with(hostname="lablink-vm-test-1")


def test_get_vm_status_by_hostname_not_found(client, monkeypatch):
    """Test getting VM status by hostname when not found."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_status_by_hostname.return_value = None
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    resp = client.get("/api/vm-status/lablink-vm-nonexistent")

    assert resp.status_code == 404
    assert resp.is_json
    assert resp.get_json() == {"error": "VM not found."}
    fake_db.get_status_by_hostname.assert_called_once_with(
        hostname="lablink-vm-nonexistent"
    )


def test_get_vm_status_by_hostname_internal_error(client, monkeypatch):
    """Test getting VM status by hostname with internal error."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_status_by_hostname.side_effect = Exception("Internal error")
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    resp = client.get("/api/vm-status/lablink-vm-test-1")

    assert resp.status_code == 500
    assert resp.is_json
    assert resp.get_json() == {"error": "Failed to get VM status."}
    fake_db.get_status_by_hostname.assert_called_once_with(hostname="lablink-vm-test-1")


def test_get_all_vm_status_success(client, monkeypatch):
    """Test getting all VM statuses."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_all_vm_status.return_value = {
        "lablink-vm-test-1": "running",
        "lablink-vm-test-2": "initializing",
    }
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    resp = client.get(VM_STATUS_UPDATE_ENDPOINT)

    assert resp.status_code == 200
    assert resp.is_json
    assert resp.get_json() == {
        "lablink-vm-test-1": "running",
        "lablink-vm-test-2": "initializing",
    }
    fake_db.get_all_vm_status.assert_called_once()


def test_get_all_vm_status_empty(client, monkeypatch):
    """Test getting all VM statuses when empty."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_all_vm_status.return_value = {}
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    resp = client.get(VM_STATUS_UPDATE_ENDPOINT)

    assert resp.status_code == 404
    assert resp.is_json
    assert resp.get_json() == {"error": "No VMs found."}
    fake_db.get_all_vm_status.assert_called_once()


def test_get_all_vm_status_internal_error(client, monkeypatch):
    """Test getting all VM statuses with internal error."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_all_vm_status.side_effect = Exception("Internal error")
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    resp = client.get(VM_STATUS_UPDATE_ENDPOINT)

    assert resp.status_code == 500
    assert resp.is_json
    assert resp.get_json() == {"error": "Failed to get VM status."}
    fake_db.get_all_vm_status.assert_called_once()


def test_posting_vm_logs_success(client, monkeypatch):
    """Test posting VM logs successfully."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.vm_exists.return_value = True
    fake_db.get_vm_logs.return_value = "Sample log data for VM."
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    data = {
        "log_group": "cloud-init-output-logs",
        "log_stream": "lablink-vm-test-1",
        "messages": ["Message 1", "Message 2"],
    }
    resp = client.post(VM_LOGS_ENDPOINT, json=data)

    assert resp.status_code == 200
    assert resp.is_json
    assert resp.get_json() == {"message": "VM logs posted successfully."}
    fake_db.vm_exists.assert_called_once_with("lablink-vm-test-1")
    fake_db.get_vm_logs.assert_called_once_with(hostname="lablink-vm-test-1")
    fake_db.save_logs_by_hostname.assert_called_once_with(
        hostname="lablink-vm-test-1",
        logs="Sample log data for VM.\nMessage 1\nMessage 2",
    )


def test_posting_vm_logs_missing_data(client, monkeypatch):
    """Test posting VM logs with missing data."""
    # Mock the database
    fake_db = MagicMock()
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API with missing data
    resp = client.post(VM_LOGS_ENDPOINT, json={})

    assert resp.status_code == 400
    assert resp.is_json
    assert resp.get_json() == {"error": "Log group, stream, and messages are required."}
    fake_db.vm_exists.assert_not_called()
    fake_db.get_vm_logs.assert_not_called()
    fake_db.save_logs_by_hostname.assert_not_called()


def test_posting_vm_logs_vm_not_exists(client, monkeypatch):
    """Test posting VM logs when VM does not exist."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.vm_exists.return_value = False
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    data = {
        "log_group": "cloud-init-output-logs",
        "log_stream": "lablink-vm-test-1",
        "messages": ["Message 1", "Message 2"],
    }
    resp = client.post(VM_LOGS_ENDPOINT, json=data)

    assert resp.status_code == 404
    assert resp.is_json
    assert resp.get_json() == {"error": "VM not found."}
    fake_db.vm_exists.assert_called_once_with("lablink-vm-test-1")
    fake_db.get_vm_logs.assert_not_called()
    fake_db.save_logs_by_hostname.assert_not_called()


def test_posting_vm_logs_internal_error(client, monkeypatch):
    """Test posting VM logs with internal error."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.vm_exists.side_effect = Exception("Internal error")
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    data = {
        "log_group": "cloud-init-output-logs",
        "log_stream": "lablink-vm-test-1",
        "messages": ["Message 1", "Message 2"],
    }
    resp = client.post(VM_LOGS_ENDPOINT, json=data)

    assert resp.status_code == 500
    assert resp.is_json
    assert resp.get_json() == {"error": "Failed to post VM logs."}
    fake_db.vm_exists.assert_called_once_with("lablink-vm-test-1")
    fake_db.get_vm_logs.assert_not_called()
    fake_db.save_logs_by_hostname.assert_not_called()


def test_get_vm_logs_by_hostname_success(client, monkeypatch):
    """Test getting VM logs by hostname successfully."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_vm_by_hostname.return_value = {
        "hostname": "lablink-vm-test-1",
        "logs": "Sample log data for VM.",
    }
    fake_db.get_vm_logs.return_value = "Sample log data for VM."
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    resp = client.get(f"{VM_LOGS_ENDPOINT}/lablink-vm-test-1")

    assert resp.status_code == 200
    assert resp.is_json
    assert resp.get_json() == {
        "hostname": "lablink-vm-test-1",
        "logs": "Sample log data for VM.",
    }
    fake_db.get_vm_logs.assert_called_once_with(hostname="lablink-vm-test-1")


def test_vm_logs_by_hostname_not_found(client, monkeypatch):
    """Test getting VM logs by hostname when not found."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_vm_by_hostname.return_value = None
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    resp = client.get(f"{VM_LOGS_ENDPOINT}/lablink-vm-test-1")

    assert resp.status_code == 404
    assert resp.is_json
    assert resp.get_json() == {"error": "VM not found."}
    fake_db.get_vm_logs.assert_not_called()


def test_vm_logs_by_hostname_installing_cloud_watch(client, monkeypatch):
    """Test getting VM logs by hostname when installing CloudWatch agent."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_vm_by_hostname.return_value = {
        "hostname": "lablink-vm-test-1",
        "status": "initializing",
    }
    fake_db.get_vm_logs.return_value = None
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    resp = client.get(f"{VM_LOGS_ENDPOINT}/lablink-vm-test-1")

    assert resp.status_code == 503
    assert resp.is_json
    assert resp.get_json() == {"error": "VM is installing CloudWatch agent."}


def test_vm_logs_by_hostname_internal_error(client, monkeypatch):
    """Test getting VM logs by hostname with internal error."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_vm_by_hostname.side_effect = Exception("Internal error")
    monkeypatch.setattr("main.database", fake_db, raising=False)

    # Call the API
    resp = client.get(f"{VM_LOGS_ENDPOINT}/lablink-vm-test-1")

    assert resp.status_code == 500
    assert resp.is_json
    assert resp.get_json() == {"error": "Failed to get VM logs."}
    fake_db.get_vm_logs.assert_not_called()
