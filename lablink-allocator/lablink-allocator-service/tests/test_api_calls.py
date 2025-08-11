from unittest.mock import patch, MagicMock
import json

VM_STARTUP_ENDPOINT = "/vm_startup"
UNASSIGNED_VMS_COUNT_ENDPOINT = "/api/unassigned_vms_count"
UPDATE_INUSE_STATUS_ENDPOINT = "/api/update_inuse_status"
UPDATE_GPU_HEALTH_ENDPOINT = "/api/gpu_health"


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
    fake_db.insert_vm.assert_called_once_with(hostname="test-vm-dev-1")
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
