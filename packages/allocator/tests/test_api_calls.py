from unittest.mock import MagicMock
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
METRICS_ENDPOINT = "/api/vm-metrics"
SCHEDULE_DESTRUCTION_ENDPOINT = "/api/schedule-destruction"


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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API
    data = {"hostname": "test-vm-dev-1", "gpu_status": "Healthy"}
    resp = client.post(UPDATE_GPU_HEALTH_ENDPOINT, json=data)

    # Assert the response
    assert resp.status_code == 200
    assert resp.get_json() == {"message": "GPU health status updated successfully."}
    fake_db.update_health.assert_called_once_with(
        hostname="test-vm-dev-1", healthy="Healthy"
    )


def test_update_gpu_health_failure(client, monkeypatch):
    """Test the /api/gpu_health endpoint with database internal failure."""
    # Mock the database
    fake_db = MagicMock()

    # Failure while update gpu health
    fake_db.update_health.side_effect = Exception("Database internal error")

    # Patch the database
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    check_crd = lambda crd_command: True  # noqa: E731
    monkeypatch.setattr(
        "lablink_allocator_service.main.check_crd_input", check_crd, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.check_crd_input",
        lambda crd_command: False,
        raising=False,
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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    check_crd = lambda crd_command: True  # noqa: E731
    monkeypatch.setattr(
        "lablink_allocator_service.main.check_crd_input", check_crd, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    check_crd = lambda crd_command: True  # noqa: E731
    monkeypatch.setattr(
        "lablink_allocator_service.main.check_crd_input", check_crd, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.get_instance_ips",
        lambda terraform_dir: ["10.0.0.1"],
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.get_ssh_private_key",
        lambda terraform_dir: "/tmp/key.pem",
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.find_files_in_container",
        lambda ip, key_path, extension: ["/remote/path/sample.slp"],
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.extract_files_from_docker",
        lambda **kwargs: None,
    )

    # Dummy function for rsync
    def fake_rsync(ip, key_path, local_dir, extension="slp"):
        Path(local_dir).mkdir(parents=True, exist_ok=True)
        (Path(local_dir) / f"sample.{extension}").write_text("dummy")

    monkeypatch.setattr(
        "lablink_allocator_service.main.rsync_files_to_allocator", fake_rsync
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Two IPs
    monkeypatch.setattr(
        "lablink_allocator_service.main.get_instance_ips",
        lambda terraform_dir: ["10.0.0.1", "10.0.0.2"],
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.get_ssh_private_key",
        lambda terraform_dir: "/tmp/key.pem",
    )

    # Create MagicMocks for each function
    find_slp = MagicMock(return_value=["/remote/path/sample.slp"])
    extract = MagicMock()
    rsync = MagicMock(
        side_effect=lambda ip, key_path, local_dir, extension: (
            Path(local_dir).mkdir(parents=True, exist_ok=True),
            (Path(local_dir) / f"sample.{extension}").write_text("dummy"),
        )
    )

    # Use MagicMocks so we can assert call counts/args
    monkeypatch.setattr(
        "lablink_allocator_service.main.find_files_in_container",
        find_slp,
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.extract_files_from_docker",
        extract,
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.rsync_files_to_allocator", rsync, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Mock the utility functions
    monkeypatch.setattr(
        "lablink_allocator_service.main.get_instance_ips",
        lambda terraform_dir: ["10.0.0.1", "10.0.0.2"],
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.get_ssh_private_key",
        lambda terraform_dir: "/tmp/key.pem",
    )

    # First VM has .slp files; second has none
    def find_side_effect(ip, key_path, extension):
        return ["/remote/sample.slp"] if ip == "10.0.0.1" else []

    # Mock the file operations
    find_slp = MagicMock(side_effect=find_side_effect)
    extract = MagicMock()
    rsync = MagicMock(
        side_effect=lambda ip, key_path, local_dir, extension: (
            Path(local_dir).mkdir(parents=True, exist_ok=True),
            (Path(local_dir) / "sample.slp").write_text("dummy"),
        )
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.find_files_in_container",
        find_slp,
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.extract_files_from_docker",
        extract,
        raising=False,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.rsync_files_to_allocator", rsync, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.get_instance_ips",
        lambda terraform_dir: ["10.0.0.1"],
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.get_ssh_private_key",
        lambda terraform_dir: "/tmp/key.pem",
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.find_files_in_container",
        lambda ip, key_path, extension: [],
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.extract_files_from_docker",
        lambda **kwargs: None,
    )

    # Call the API
    resp = client.get(SCP_ENDPOINT, headers=admin_headers)
    assert resp.status_code == 404
    assert resp.is_json
    assert resp.get_json() == {"error": "No slp files found in any VMs."}


def test_scp_internal_failure(client, admin_headers, monkeypatch, tmp_path):
    # DB has rows
    fake_db = MagicMock()
    fake_db.get_row_count.return_value = 1
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    monkeypatch.chdir(tmp_path)
    Path("terraform").mkdir(exist_ok=True)

    monkeypatch.setattr(
        "lablink_allocator_service.main.get_instance_ips",
        lambda terraform_dir: ["10.0.0.1"],
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.get_ssh_private_key",
        lambda terraform_dir: "/tmp/key.pem",
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.find_files_in_container",
        lambda ip, key_path, extension: ["/remote/sample.slp"],
    )

    # Make one of the steps raise a CalledProcessError to trigger 500 path
    def explode(**kwargs):
        raise subprocess.CalledProcessError(1, ["rsync"], "boom")

    monkeypatch.setattr(
        "lablink_allocator_service.main.extract_files_from_docker", explode
    )

    resp = client.get(SCP_ENDPOINT, headers=admin_headers)
    assert resp.status_code == 500
    assert resp.is_json
    assert "downloading data from VMs" in resp.get_json()["error"]


def test_update_vm_status_success(client, monkeypatch):
    """Test successful VM status update."""
    # Mock the database
    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

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
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API
    resp = client.get(f"{VM_LOGS_ENDPOINT}/lablink-vm-test-1")

    assert resp.status_code == 500
    assert resp.is_json
    assert resp.get_json() == {"error": "Failed to get VM logs."}
    fake_db.get_vm_logs.assert_not_called()


def test_receive_vm_metrics_success(client, monkeypatch):
    """Test the /api/vm-metrics/<hostname> endpoint with valid data."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.vm_exists.return_value = True

    # Patch globals
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API
    hostname = "test-vm-01"
    metrics_data = {
        "cloud_init_start": 1672531200,
        "cloud_init_end": 1672531320,
        "cloud_init_duration_seconds": 120,
    }
    resp = client.post(f"{METRICS_ENDPOINT}/{hostname}", json=metrics_data)

    # Assert the response
    assert resp.status_code == 200
    assert resp.get_json() == {"message": "VM metrics posted successfully."}
    fake_db.vm_exists.assert_called_once_with(hostname=hostname)
    # Updated to use atomic method
    fake_db.update_vm_metrics_atomic.assert_called_once_with(
        hostname=hostname, metrics=metrics_data
    )


def test_receive_vm_metrics_vm_not_found(client, monkeypatch):
    """Test the /api/vm-metrics/<hostname> endpoint when the VM is not found."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.vm_exists.return_value = False

    # Patch globals
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API
    hostname = "non-existent-vm"
    metrics_data = {"cloud_init_duration_seconds": 120}
    resp = client.post(f"{METRICS_ENDPOINT}/{hostname}", json=metrics_data)

    # Assert the response
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "VM not found."}
    fake_db.vm_exists.assert_called_once_with(hostname=hostname)
    fake_db.update_vm_metrics_atomic.assert_not_called()


def test_receive_vm_metrics_internal_error(client, monkeypatch):
    """Test the /api/vm-metrics/<hostname> endpoint with an internal error."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.vm_exists.return_value = True
    fake_db.update_vm_metrics_atomic.side_effect = Exception("Database error")

    # Patch globals
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API
    hostname = "test-vm-01"
    metrics_data = {"cloud_init_duration_seconds": 120}
    resp = client.post(f"{METRICS_ENDPOINT}/{hostname}", json=metrics_data)

    # Assert the response
    assert resp.status_code == 500
    assert resp.get_json() == {"error": "Failed to post VM metrics."}
    fake_db.vm_exists.assert_called_once_with(hostname=hostname)
    fake_db.update_vm_metrics_atomic.assert_called_once_with(
        hostname=hostname, metrics=metrics_data
    )


def test_receive_vm_metrics_concurrent(client, monkeypatch):
    """Test that concurrent metrics requests are handled correctly."""
    import concurrent.futures

    # Mock the database
    fake_db = MagicMock()
    fake_db.vm_exists.return_value = True

    # Patch globals
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Create 10 concurrent requests
    def send_metrics(vm_id):
        hostname = f"test-vm-{vm_id:02d}"
        metrics_data = {
            "cloud_init_start": 1672531200 + vm_id,
            "cloud_init_end": 1672531320 + vm_id,
            "cloud_init_duration_seconds": 120,
        }
        return client.post(f"{METRICS_ENDPOINT}/{hostname}", json=metrics_data)

    # Send all requests concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        responses = list(executor.map(send_metrics, range(10)))

    # All should succeed
    assert all(r.status_code == 200 for r in responses)
    assert all(
        r.get_json() == {"message": "VM metrics posted successfully."}
        for r in responses
    )

    # Verify all VMs were checked and updated
    assert fake_db.vm_exists.call_count == 10
    assert fake_db.update_vm_metrics_atomic.call_count == 10


def test_create_scheduled_destruction_success(client, admin_headers, monkeypatch):
    """Test creating a scheduled destruction with valid data."""
    from datetime import datetime, timedelta, timezone

    # Mock the database and scheduler
    fake_db = MagicMock()
    fake_scheduler = MagicMock()
    fake_scheduler.schedule_destruction.return_value = 123

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.scheduler_service",
        fake_scheduler,
        raising=False,
    )

    # Call the API with a future date
    future_time = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    data = {
        "schedule_name": "Friday Tutorial End",
        "destruction_time": future_time,
        "recurrence_rule": None,
        "notification_enabled": True,
        "notification_hours_before": 1,
    }
    resp = client.post(SCHEDULE_DESTRUCTION_ENDPOINT, json=data, headers=admin_headers)

    # Assert response
    assert resp.status_code == 201
    assert resp.is_json
    json_data = resp.get_json()
    assert json_data["success"] is True
    assert json_data["schedule_id"] == 123
    assert "successfully" in json_data["message"]

    # Verify scheduler was called correctly
    fake_scheduler.schedule_destruction.assert_called_once()
    call_kwargs = fake_scheduler.schedule_destruction.call_args.kwargs
    assert call_kwargs["schedule_name"] == "Friday Tutorial End"
    assert isinstance(call_kwargs["destruction_time"], datetime)
    assert call_kwargs["recurrence_rule"] is None
    assert call_kwargs["notification_enabled"] is True
    assert call_kwargs["notification_hours_before"] == 1


def test_create_scheduled_destruction_with_recurrence(
    client, admin_headers, monkeypatch
):
    """Test creating a recurring scheduled destruction."""
    from datetime import datetime, timedelta, timezone

    # Mock the scheduler
    fake_db = MagicMock()
    fake_scheduler = MagicMock()
    fake_scheduler.schedule_destruction.return_value = 456

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.scheduler_service",
        fake_scheduler,
        raising=False,
    )

    # Call the API with recurrence rule and future date
    future_time = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    data = {
        "schedule_name": "Weekly Friday Cleanup",
        "destruction_time": future_time,
        "recurrence_rule": "FREQ=WEEKLY;BYDAY=FR;BYHOUR=17;BYMINUTE=30",
    }
    resp = client.post(SCHEDULE_DESTRUCTION_ENDPOINT, json=data, headers=admin_headers)

    # Assert response
    assert resp.status_code == 201
    assert resp.get_json()["success"] is True
    assert resp.get_json()["schedule_id"] == 456

    # Verify recurrence rule was passed
    call_kwargs = fake_scheduler.schedule_destruction.call_args.kwargs
    assert call_kwargs["recurrence_rule"] == "FREQ=WEEKLY;BYDAY=FR;BYHOUR=17;BYMINUTE=30"


def test_create_scheduled_destruction_missing_fields(
    client, admin_headers, monkeypatch
):
    """Test creating a scheduled destruction with missing required fields."""
    fake_db = MagicMock()
    fake_scheduler = MagicMock()

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.scheduler_service",
        fake_scheduler,
        raising=False,
    )

    # Missing schedule_name
    data = {"destruction_time": "2025-12-05T17:30:00Z"}
    resp = client.post(SCHEDULE_DESTRUCTION_ENDPOINT, json=data, headers=admin_headers)

    assert resp.status_code == 400
    assert resp.get_json()["success"] is False
    assert "schedule_name is required" in resp.get_json()["message"]
    fake_scheduler.schedule_destruction.assert_not_called()


def test_create_scheduled_destruction_invalid_date_format(
    client, admin_headers, monkeypatch
):
    """Test creating a scheduled destruction with invalid date format."""
    fake_db = MagicMock()
    fake_scheduler = MagicMock()

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.scheduler_service",
        fake_scheduler,
        raising=False,
    )

    # Invalid date format
    data = {
        "schedule_name": "Bad Date",
        "destruction_time": "not-a-valid-date",
    }
    resp = client.post(SCHEDULE_DESTRUCTION_ENDPOINT, json=data, headers=admin_headers)

    assert resp.status_code == 400
    assert resp.get_json()["success"] is False
    assert "Invalid destruction_time format" in resp.get_json()["message"]
    fake_scheduler.schedule_destruction.assert_not_called()


def test_create_scheduled_destruction_past_date(client, admin_headers, monkeypatch):
    """Test creating a scheduled destruction with a past date."""
    fake_db = MagicMock()
    fake_scheduler = MagicMock()

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.scheduler_service",
        fake_scheduler,
        raising=False,
    )

    # Past date
    data = {
        "schedule_name": "Past Date",
        "destruction_time": "2020-01-01T12:00:00Z",
    }
    resp = client.post(SCHEDULE_DESTRUCTION_ENDPOINT, json=data, headers=admin_headers)

    assert resp.status_code == 400
    assert resp.get_json()["success"] is False
    assert "must be in the future" in resp.get_json()["message"]
    fake_scheduler.schedule_destruction.assert_not_called()


def test_create_scheduled_destruction_scheduler_unavailable(
    client, admin_headers, monkeypatch
):
    """Test creating a scheduled destruction when scheduler is unavailable."""
    from datetime import datetime, timedelta, timezone

    fake_db = MagicMock()

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.scheduler_service", None, raising=False
    )

    future_time = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    data = {
        "schedule_name": "Test",
        "destruction_time": future_time,
    }
    resp = client.post(SCHEDULE_DESTRUCTION_ENDPOINT, json=data, headers=admin_headers)

    assert resp.status_code == 500
    assert resp.get_json()["success"] is False
    assert "not initialized" in resp.get_json()["message"]


def test_create_scheduled_destruction_scheduler_error(
    client, admin_headers, monkeypatch
):
    """Test creating a scheduled destruction when scheduler raises error."""
    from datetime import datetime, timedelta, timezone

    fake_db = MagicMock()
    fake_scheduler = MagicMock()
    fake_scheduler.schedule_destruction.side_effect = RuntimeError(
        "Failed to create scheduled destruction 'Test'"
    )

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.scheduler_service",
        fake_scheduler,
        raising=False,
    )

    future_time = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    data = {
        "schedule_name": "Test",
        "destruction_time": future_time,
    }
    resp = client.post(SCHEDULE_DESTRUCTION_ENDPOINT, json=data, headers=admin_headers)

    assert resp.status_code == 500
    assert resp.get_json()["success"] is False
    # API returns str(e) which is the RuntimeError message
    assert "Failed to create scheduled destruction" in resp.get_json()["message"]


def test_create_scheduled_destruction_requires_auth(client, monkeypatch):
    """Test that creating a scheduled destruction requires authentication."""
    fake_db = MagicMock()
    fake_scheduler = MagicMock()

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.scheduler_service",
        fake_scheduler,
        raising=False,
    )

    data = {
        "schedule_name": "Test",
        "destruction_time": "2025-12-05T17:30:00Z",
    }
    resp = client.post(SCHEDULE_DESTRUCTION_ENDPOINT, json=data)

    assert resp.status_code == 401
    fake_scheduler.schedule_destruction.assert_not_called()


def test_get_scheduled_destruction_success(client, admin_headers, monkeypatch):
    """Test getting details of a scheduled destruction."""
    fake_db = MagicMock()
    fake_db.get_scheduled_destruction.return_value = {
        "id": 123,
        "schedule_name": "Friday Tutorial End",
        "destruction_time": "2025-12-05T17:30:00Z",
        "recurrence_rule": None,
        "status": "scheduled",
        "created_by": "admin",
    }

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.get(f"{SCHEDULE_DESTRUCTION_ENDPOINT}/123", headers=admin_headers)

    assert resp.status_code == 200
    assert resp.is_json
    json_data = resp.get_json()
    assert json_data["success"] is True
    assert json_data["schedule"]["id"] == 123
    assert json_data["schedule"]["schedule_name"] == "Friday Tutorial End"
    fake_db.get_scheduled_destruction.assert_called_once_with(123)


def test_get_scheduled_destruction_not_found(client, admin_headers, monkeypatch):
    """Test getting a non-existent scheduled destruction."""
    fake_db = MagicMock()
    fake_db.get_scheduled_destruction.return_value = None

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.get(f"{SCHEDULE_DESTRUCTION_ENDPOINT}/999", headers=admin_headers)

    assert resp.status_code == 404
    assert resp.get_json()["success"] is False
    assert "not found" in resp.get_json()["message"]


def test_get_scheduled_destruction_requires_auth(client, monkeypatch):
    """Test that getting a scheduled destruction requires authentication."""
    fake_db = MagicMock()

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.get(f"{SCHEDULE_DESTRUCTION_ENDPOINT}/123")

    assert resp.status_code == 401
    fake_db.get_scheduled_destruction.assert_not_called()


def test_list_scheduled_destructions_success(client, admin_headers, monkeypatch):
    """Test listing all scheduled destructions."""
    fake_db = MagicMock()
    fake_db.get_all_scheduled_destructions.return_value = [
        {
            "id": 1,
            "schedule_name": "Schedule 1",
            "status": "scheduled",
        },
        {
            "id": 2,
            "schedule_name": "Schedule 2",
            "status": "completed",
        },
    ]

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.get(SCHEDULE_DESTRUCTION_ENDPOINT, headers=admin_headers)

    assert resp.status_code == 200
    assert resp.is_json
    json_data = resp.get_json()
    assert json_data["success"] is True
    assert len(json_data["schedules"]) == 2
    fake_db.get_all_scheduled_destructions.assert_called_once_with(status=None)


def test_list_scheduled_destructions_with_filter(client, admin_headers, monkeypatch):
    """Test listing scheduled destructions with status filter."""
    fake_db = MagicMock()
    fake_db.get_all_scheduled_destructions.return_value = [
        {
            "id": 1,
            "schedule_name": "Schedule 1",
            "status": "scheduled",
        },
    ]

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.get(
        f"{SCHEDULE_DESTRUCTION_ENDPOINT}?status=scheduled", headers=admin_headers
    )

    assert resp.status_code == 200
    assert resp.is_json
    json_data = resp.get_json()
    assert json_data["success"] is True
    assert len(json_data["schedules"]) == 1
    fake_db.get_all_scheduled_destructions.assert_called_once_with(status="scheduled")


def test_list_scheduled_destructions_invalid_status(client, admin_headers, monkeypatch):
    """Test listing scheduled destructions with invalid status filter."""
    fake_db = MagicMock()

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.get(
        f"{SCHEDULE_DESTRUCTION_ENDPOINT}?status=invalid_status", headers=admin_headers
    )

    assert resp.status_code == 400
    assert resp.get_json()["success"] is False
    assert "Invalid status" in resp.get_json()["message"]
    fake_db.get_all_scheduled_destructions.assert_not_called()


def test_list_scheduled_destructions_requires_auth(client, monkeypatch):
    """Test that listing scheduled destructions requires authentication."""
    fake_db = MagicMock()

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.get(SCHEDULE_DESTRUCTION_ENDPOINT)

    assert resp.status_code == 401
    fake_db.get_all_scheduled_destructions.assert_not_called()


def test_cancel_scheduled_destruction_success(client, admin_headers, monkeypatch):
    """Test canceling a scheduled destruction."""
    fake_db = MagicMock()
    fake_db.get_scheduled_destruction.return_value = {
        "id": 123,
        "schedule_name": "Test Schedule",
        "status": "scheduled",
    }

    fake_scheduler = MagicMock()

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.scheduler_service",
        fake_scheduler,
        raising=False,
    )

    resp = client.delete(f"{SCHEDULE_DESTRUCTION_ENDPOINT}/123", headers=admin_headers)

    assert resp.status_code == 200
    assert resp.is_json
    assert resp.get_json()["success"] is True
    assert "cancelled" in resp.get_json()["message"]
    fake_scheduler.cancel_scheduled_destruction.assert_called_once_with(123)


def test_cancel_scheduled_destruction_not_found(client, admin_headers, monkeypatch):
    """Test canceling a non-existent scheduled destruction."""
    fake_db = MagicMock()
    fake_db.get_scheduled_destruction.return_value = None

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.delete(f"{SCHEDULE_DESTRUCTION_ENDPOINT}/999", headers=admin_headers)

    assert resp.status_code == 404
    assert resp.get_json()["success"] is False
    assert "not found" in resp.get_json()["message"]


def test_cancel_scheduled_destruction_already_completed(
    client, admin_headers, monkeypatch
):
    """Test canceling a completed scheduled destruction."""
    fake_db = MagicMock()
    fake_db.get_scheduled_destruction.return_value = {
        "id": 123,
        "schedule_name": "Test Schedule",
        "status": "completed",
    }

    fake_scheduler = MagicMock()

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.scheduler_service",
        fake_scheduler,
        raising=False,
    )

    resp = client.delete(f"{SCHEDULE_DESTRUCTION_ENDPOINT}/123", headers=admin_headers)

    assert resp.status_code == 400
    assert resp.get_json()["success"] is False
    assert "Cannot cancel schedule with status 'completed'" in resp.get_json()["message"]
    fake_scheduler.cancel_scheduled_destruction.assert_not_called()


def test_cancel_scheduled_destruction_already_cancelled(
    client, admin_headers, monkeypatch
):
    """Test canceling an already-cancelled scheduled destruction."""
    fake_db = MagicMock()
    fake_db.get_scheduled_destruction.return_value = {
        "id": 123,
        "schedule_name": "Test Schedule",
        "status": "cancelled",
    }

    fake_scheduler = MagicMock()

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.scheduler_service",
        fake_scheduler,
        raising=False,
    )

    resp = client.delete(f"{SCHEDULE_DESTRUCTION_ENDPOINT}/123", headers=admin_headers)

    assert resp.status_code == 400
    assert resp.get_json()["success"] is False
    assert "Cannot cancel schedule with status 'cancelled'" in resp.get_json()["message"]
    fake_scheduler.cancel_scheduled_destruction.assert_not_called()


def test_cancel_scheduled_destruction_scheduler_unavailable(
    client, admin_headers, monkeypatch
):
    """Test canceling when scheduler is unavailable."""
    fake_db = MagicMock()
    fake_db.get_scheduled_destruction.return_value = {
        "id": 123,
        "schedule_name": "Test Schedule",
        "status": "scheduled",
    }

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.scheduler_service", None, raising=False
    )

    resp = client.delete(f"{SCHEDULE_DESTRUCTION_ENDPOINT}/123", headers=admin_headers)

    assert resp.status_code == 500
    assert resp.get_json()["success"] is False
    assert "not initialized" in resp.get_json()["message"]


def test_cancel_scheduled_destruction_scheduler_error(
    client, admin_headers, monkeypatch
):
    """Test canceling when scheduler raises error."""
    fake_db = MagicMock()
    fake_db.get_scheduled_destruction.return_value = {
        "id": 123,
        "schedule_name": "Test Schedule",
        "status": "scheduled",
    }

    fake_scheduler = MagicMock()
    fake_scheduler.cancel_scheduled_destruction.side_effect = Exception(
        "Scheduler error"
    )

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.scheduler_service",
        fake_scheduler,
        raising=False,
    )

    resp = client.delete(f"{SCHEDULE_DESTRUCTION_ENDPOINT}/123", headers=admin_headers)

    assert resp.status_code == 500
    assert resp.get_json()["success"] is False
    # API returns str(e) which is "Scheduler error"
    assert "Scheduler error" in resp.get_json()["message"]


def test_cancel_scheduled_destruction_requires_auth(client, monkeypatch):
    """Test that canceling a scheduled destruction requires authentication."""
    fake_db = MagicMock()
    fake_scheduler = MagicMock()

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.scheduler_service",
        fake_scheduler,
        raising=False,
    )

    resp = client.delete(f"{SCHEDULE_DESTRUCTION_ENDPOINT}/123")

    assert resp.status_code == 401
    fake_db.get_scheduled_destruction.assert_not_called()
    fake_scheduler.cancel_scheduled_destruction.assert_not_called()


def test_create_scheduled_destruction_database_returns_none(
    client, admin_headers, monkeypatch
):
    """Test that scheduler raises error when database returns None.

    This tests the fix for the bug where database.create_scheduled_destruction
    returning None would cause silent failure and orphaned APScheduler jobs.
    """
    from datetime import datetime, timedelta, timezone

    fake_db = MagicMock()
    fake_scheduler = MagicMock()

    # Mock database to return None (simulating database error)
    fake_scheduler.schedule_destruction.side_effect = RuntimeError(
        "Failed to create scheduled destruction 'Test Schedule'"
    )

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.scheduler_service",
        fake_scheduler,
        raising=False,
    )

    future_time = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    data = {
        "schedule_name": "Test Schedule",
        "destruction_time": future_time,
    }
    resp = client.post(SCHEDULE_DESTRUCTION_ENDPOINT, json=data, headers=admin_headers)

    # Should return 500 error instead of silently failing
    assert resp.status_code == 500
    assert resp.get_json()["success"] is False
    assert "Failed to create scheduled destruction" in resp.get_json()["message"]

    # Verify scheduler was called (the error happens inside scheduler.schedule_destruction)
    fake_scheduler.schedule_destruction.assert_called_once()


def test_create_scheduled_destruction_duplicate_name(
    client, admin_headers, monkeypatch
):
    """Test creating a scheduled destruction with a duplicate name.

    This tests that duplicate schedule names (unique constraint violation)
    return a 409 Conflict with a clear error message.
    """
    from datetime import datetime, timedelta, timezone

    fake_db = MagicMock()
    fake_scheduler = MagicMock()

    # Mock scheduler to raise ValueError for duplicate name
    fake_scheduler.schedule_destruction.side_effect = ValueError(
        "A schedule with the name 'Daily Cleanup' already exists"
    )

    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.scheduler_service",
        fake_scheduler,
        raising=False,
    )

    future_time = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    data = {
        "schedule_name": "Daily Cleanup",
        "destruction_time": future_time,
    }
    resp = client.post(SCHEDULE_DESTRUCTION_ENDPOINT, json=data, headers=admin_headers)

    # Should return 409 Conflict with clear message
    assert resp.status_code == 409
    assert resp.get_json()["success"] is False
    assert "already exists" in resp.get_json()["message"]
    assert "Daily Cleanup" in resp.get_json()["message"]

    # Verify scheduler was called
    fake_scheduler.schedule_destruction.assert_called_once()
