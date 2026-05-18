from unittest.mock import MagicMock

import pytest


_TEST_CLIENT_SECRET = "test-client-secret"
_CLIENT_SECRET_HEADERS = {"Authorization": f"Bearer {_TEST_CLIENT_SECRET}"}


def _stub_client_secret(fake_db):
    """Configure fake_db so require_client_secret accepts _CLIENT_SECRET_HEADERS."""
    from lablink_allocator_service.secret_hash import hash_secret

    fake_db.get_client_secret_hash.return_value = hash_secret(_TEST_CLIENT_SECRET)
    return fake_db


UNASSIGNED_VMS_COUNT_ENDPOINT = "/api/unassigned_vms_count"
UPDATE_INUSE_STATUS_ENDPOINT = "/api/update_inuse_status"
UPDATE_GPU_HEALTH_ENDPOINT = "/api/gpu_health"
REQUEST_VM_ENDPOINT = "/api/request_vm"
VM_STATUS_UPDATE_ENDPOINT = "/api/vm-status"
VM_LOGS_ENDPOINT = "/api/vm-logs"
METRICS_ENDPOINT = "/api/vm-metrics"
SCHEDULE_DESTRUCTION_ENDPOINT = "/api/schedule-destruction"
HEARTBEAT_ENDPOINT = "/api/heartbeat"


def test_unassigned_vms_count(client, monkeypatch):
    """Test the /api/unassigned_vms_count endpoint (public, no auth required)."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_unassigned_vms.return_value = [
        {
            "hostname": "test-vm-dev-1",
            "useremail": "",
            "inuse": False,
            "healthy": "Healthy",
        },
        {
            "hostname": "test-vm-dev-2",
            "useremail": "",
            "inuse": False,
            "healthy": "Healthy",
        },
    ]

    # Patch globals
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API without auth (endpoint is public)
    resp = client.get(UNASSIGNED_VMS_COUNT_ENDPOINT)

    # Assert the response
    assert resp.status_code == 200
    assert resp.get_json() == {"count": 2}
    fake_db.get_unassigned_vms.assert_called_once()


def test_update_inuse_status_success(client, monkeypatch):
    """Test the /api/update_inuse_status endpoint."""
    # Mock the database
    fake_db = MagicMock()
    _stub_client_secret(fake_db)

    # Patch globals
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API
    data = {"hostname": "test-vm-dev-1", "status": True}
    resp = client.post(
        UPDATE_INUSE_STATUS_ENDPOINT, json=data, headers=_CLIENT_SECRET_HEADERS
    )

    # Assert the response
    assert resp.status_code == 200
    assert resp.get_json() == {"message": "In-use status updated successfully."}
    fake_db.update_vm_in_use.assert_called_once_with(
        hostname="test-vm-dev-1", in_use=True
    )


def test_update_inuse_status_missing_hostname(client, monkeypatch):
    """Test the /api/update_inuse_status endpoint with missing hostname (decorator rejects)."""
    # Mock the database
    fake_db = MagicMock()

    # Patch globals
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API — no hostname means require_client_secret returns 401
    data = {"status": True}
    resp = client.post(
        UPDATE_INUSE_STATUS_ENDPOINT, json=data, headers=_CLIENT_SECRET_HEADERS
    )

    # Assert the response
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "client identity required."
    fake_db.update_vm_in_use.assert_not_called()


def test_update_inuse_status_failure(client, monkeypatch):
    """Test the /api/update_inuse_status endpoint with database internal failure."""
    # Mock the database
    fake_db = MagicMock()
    _stub_client_secret(fake_db)

    # Failure while update inuse status
    fake_db.update_vm_in_use.side_effect = Exception("Database internal error")

    # Patch the database
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API
    data = {"hostname": "test-vm-dev-1", "status": True}
    resp = client.post(
        UPDATE_INUSE_STATUS_ENDPOINT, json=data, headers=_CLIENT_SECRET_HEADERS
    )

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
    _stub_client_secret(fake_db)

    # Patch globals
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API
    data = {"hostname": "test-vm-dev-1", "gpu_status": "Healthy"}
    resp = client.post(
        UPDATE_GPU_HEALTH_ENDPOINT, json=data, headers=_CLIENT_SECRET_HEADERS
    )

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
    _stub_client_secret(fake_db)

    # Failure while update gpu health
    fake_db.update_health.side_effect = Exception("Database internal error")

    # Patch the database
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API
    data = {"hostname": "test-vm-dev-1", "gpu_status": "Healthy"}
    resp = client.post(
        UPDATE_GPU_HEALTH_ENDPOINT, json=data, headers=_CLIENT_SECRET_HEADERS
    )

    # Assert the response
    assert resp.status_code == 500
    assert resp.get_json() == {"error": "Failed to update GPU health status."}
    fake_db.update_health.assert_called_once_with(
        hostname="test-vm-dev-1", healthy="Healthy"
    )


def test_update_gpu_health_missing_hostname(client, monkeypatch):
    """Test the /api/gpu_health endpoint with missing hostname (decorator rejects)."""
    # Mock the database
    fake_db = MagicMock()

    # Patch globals
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API — no hostname means require_client_secret returns 401
    data = {"gpu_status": "Healthy"}
    resp = client.post(
        UPDATE_GPU_HEALTH_ENDPOINT, json=data, headers=_CLIENT_SECRET_HEADERS
    )

    # Assert the response
    assert resp.status_code == 401
    assert resp.get_json()["error"] == "client identity required."
    fake_db.update_health.assert_not_called()


def test_request_vm_success(client, monkeypatch):
    """POST /api/request_vm with valid email -> 303 to /desktop + signed cookie."""
    fake_db = MagicMock()
    fake_db.get_assigned_vm_for_email.return_value = {
        "hostname": "host1",
        "status": "running",
        "reboot_count": 0,
    }
    # The handler also borrows a raw connection to read the cookie secret.
    fake_conn = MagicMock()
    fake_db._pool.getconn.return_value = fake_conn
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=True
    )
    monkeypatch.setattr(
        "lablink_allocator_service.providers.connectivity.allocator_proxied.prepare_browser_session",
        lambda **kw: None,
    )
    monkeypatch.setattr(
        "lablink_allocator_service.main.get_or_create_cookie_secret",
        lambda conn: "test-secret",
    )

    resp = client.post(
        "/api/request_vm",
        data={"email": "user@example.com"},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert resp.headers["Location"].endswith("/desktop")
    set_cookie = resp.headers.get("Set-Cookie", "")
    assert "lablink_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=Strict" in set_cookie


def test_request_vm_missing(client, monkeypatch):
    """POST /api/request_vm with missing email -> index.html with error."""
    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=True
    )

    resp = client.post(
        "/api/request_vm",
        data={},  # no email
        follow_redirects=False,
    )

    assert resp.status_code == 200  # renders the index.html error page
    assert b"Email is required" in resp.data


def test_request_vm_no_vm_available(client, monkeypatch):
    """POST /api/request_vm when assign_vm raises ValueError -> 503."""
    fake_db = MagicMock()
    fake_db.get_assigned_vm_for_email.return_value = None
    fake_db.assign_vm.side_effect = ValueError("No available VMs to assign.")
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=True
    )

    resp = client.post(
        "/api/request_vm",
        data={"email": "user@example.com"},
        follow_redirects=False,
    )

    assert resp.status_code == 503
    assert b"No seats available" in resp.data


def test_request_vm_database_internal_failure(client, monkeypatch):
    """When the database lookup raises -> generic index.html error page."""
    fake_db = MagicMock()
    fake_db.get_assigned_vm_for_email.side_effect = Exception("Database error")
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=True
    )

    resp = client.post(
        "/api/request_vm",
        data={"email": "user@example.com"},
        follow_redirects=False,
    )

    assert resp.status_code == 200
    assert b"An unexpected error" in resp.data
    fake_db.assign_vm.assert_not_called()


def test_request_vm_rotation_failure_marks_unhealthy(client, monkeypatch):
    """When prepare_browser_session raises RotationFailed -> 503, the
    VM is marked Unhealthy AND the seat is released.

    The release_seat call is what prevents the rejoin branch from
    matching the same wedged row on retry and looping the student
    through rotation_failed forever — without it, the row keeps
    status='running' and useremail=<student>, so the next POST to
    /api/request_vm re-enters prepare_browser_session and fails the
    same way."""
    from lablink_allocator_service.client_session import RotationFailed

    fake_db = MagicMock()
    fake_db.get_assigned_vm_for_email.return_value = {
        "hostname": "host1",
        "status": "running",
        "reboot_count": 0,
    }
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=True
    )

    def _raise(**kw):
        raise RotationFailed("agent unreachable")

    monkeypatch.setattr(
        "lablink_allocator_service.providers.connectivity.allocator_proxied.prepare_browser_session",
        _raise,
    )

    resp = client.post(
        "/api/request_vm",
        data={"email": "user@example.com"},
        follow_redirects=False,
    )

    assert resp.status_code == 503
    assert b"Couldn't prepare your seat" in resp.data
    fake_db.update_health.assert_called_once_with(
        hostname="host1", healthy="Unhealthy"
    )
    fake_db.release_seat.assert_called_once_with(hostname="host1")


def test_update_vm_status_success(client, monkeypatch):
    """Test successful VM status update."""
    # Mock the database
    fake_db = MagicMock()
    _stub_client_secret(fake_db)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API
    resp = client.post(
        VM_STATUS_UPDATE_ENDPOINT,
        json={"hostname": "lablink-vm-test-1", "status": "running"},
        headers=_CLIENT_SECRET_HEADERS,
    )

    assert resp.status_code == 200
    assert resp.is_json
    assert resp.get_json() == {"message": "VM status updated successfully."}
    fake_db.update_vm_status.assert_called_once_with(
        hostname="lablink-vm-test-1", status="running"
    )


def test_update_vm_status_missing_fields(client, monkeypatch):
    """Test VM status update with missing fields (decorator rejects — no identity)."""
    # Mock the database
    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API without the hostname — require_client_secret returns 401
    resp = client.post(
        VM_STATUS_UPDATE_ENDPOINT,
        json={"status": "running"},
        headers=_CLIENT_SECRET_HEADERS,
    )

    assert resp.status_code == 401
    assert resp.is_json
    assert resp.get_json()["error"] == "client identity required."
    fake_db.update_vm_status.assert_not_called()


def test_update_vm_status_internal_failure(client, monkeypatch):
    """Test VM status update with internal failure."""
    # Mock the database
    fake_db = MagicMock()
    _stub_client_secret(fake_db)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Simulate an internal error
    fake_db.update_vm_status.side_effect = Exception("Internal error")

    # Call the API with valid data
    resp = client.post(
        VM_STATUS_UPDATE_ENDPOINT,
        json={"hostname": "lablink-vm-test-1", "status": "running"},
        headers=_CLIENT_SECRET_HEADERS,
    )

    assert resp.status_code == 500
    assert resp.is_json
    assert resp.get_json() == {"error": "Failed to update VM status."}


def test_get_all_vm_status_success(client, api_token_headers, monkeypatch):
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
    resp = client.get(VM_STATUS_UPDATE_ENDPOINT, headers=api_token_headers)

    assert resp.status_code == 200
    assert resp.is_json
    assert resp.get_json() == {
        "lablink-vm-test-1": "running",
        "lablink-vm-test-2": "initializing",
    }
    fake_db.get_all_vm_status.assert_called_once()


def test_get_all_vm_status_empty(client, api_token_headers, monkeypatch):
    """Test getting all VM statuses when empty."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_all_vm_status.return_value = {}
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API
    resp = client.get(VM_STATUS_UPDATE_ENDPOINT, headers=api_token_headers)

    assert resp.status_code == 404
    assert resp.is_json
    assert resp.get_json() == {"error": "No VMs found."}
    fake_db.get_all_vm_status.assert_called_once()


def test_get_all_vm_status_internal_error(client, api_token_headers, monkeypatch):
    """Test getting all VM statuses with internal error."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_all_vm_status.side_effect = Exception("Internal error")
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API
    resp = client.get(VM_STATUS_UPDATE_ENDPOINT, headers=api_token_headers)

    assert resp.status_code == 500
    assert resp.is_json
    assert resp.get_json() == {"error": "Failed to get VM status."}
    fake_db.get_all_vm_status.assert_called_once()


def test_posting_vm_logs_success(client, api_token_headers, monkeypatch):
    """Test posting VM logs successfully (cloud-init)."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.vm_exists.return_value = True
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API
    data = {
        "log_group": "cloud-init-output-logs",
        "log_stream": "lablink-vm-test-1",
        "messages": ["Message 1", "Message 2"],
    }
    resp = client.post(VM_LOGS_ENDPOINT, json=data, headers=api_token_headers)

    assert resp.status_code == 200
    assert resp.is_json
    assert resp.get_json() == {"message": "VM logs posted successfully."}
    fake_db.vm_exists.assert_called_once_with("lablink-vm-test-1")
    fake_db.append_logs_by_hostname.assert_called_once_with(
        hostname="lablink-vm-test-1",
        new_logs="Message 1\nMessage 2",
        log_type="cloud_init",
        max_size=1 * 1024 * 1024,
    )


def test_posting_docker_logs_success(client, api_token_headers, monkeypatch):
    """Test posting VM logs successfully (docker)."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.vm_exists.return_value = True
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API with log_group ending in -docker
    data = {
        "log_group": "cloud-init-output-logs-docker",
        "log_stream": "lablink-vm-test-1",
        "messages": ["Docker msg 1"],
    }
    resp = client.post(VM_LOGS_ENDPOINT, json=data, headers=api_token_headers)

    assert resp.status_code == 200
    assert resp.is_json
    assert resp.get_json() == {"message": "VM logs posted successfully."}
    fake_db.append_logs_by_hostname.assert_called_once_with(
        hostname="lablink-vm-test-1",
        new_logs="Docker msg 1",
        log_type="docker",
        max_size=1 * 1024 * 1024,
    )


def test_posting_vm_logs_missing_data(client, api_token_headers, monkeypatch):
    """Test posting VM logs with missing data."""
    # Mock the database
    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API with missing data
    resp = client.post(VM_LOGS_ENDPOINT, json={}, headers=api_token_headers)

    assert resp.status_code == 400
    assert resp.is_json
    assert resp.get_json() == {"error": "Log group, stream, and messages are required."}
    fake_db.vm_exists.assert_not_called()
    fake_db.append_logs_by_hostname.assert_not_called()


def test_posting_vm_logs_vm_not_exists(client, api_token_headers, monkeypatch):
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
    resp = client.post(VM_LOGS_ENDPOINT, json=data, headers=api_token_headers)

    assert resp.status_code == 404
    assert resp.is_json
    assert resp.get_json() == {"error": "VM not found."}
    fake_db.vm_exists.assert_called_once_with("lablink-vm-test-1")
    fake_db.append_logs_by_hostname.assert_not_called()


def test_posting_vm_logs_internal_error(client, api_token_headers, monkeypatch):
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
    resp = client.post(VM_LOGS_ENDPOINT, json=data, headers=api_token_headers)

    assert resp.status_code == 500
    assert resp.is_json
    assert resp.get_json() == {"error": "Failed to post VM logs."}
    fake_db.vm_exists.assert_called_once_with("lablink-vm-test-1")
    fake_db.append_logs_by_hostname.assert_not_called()


def test_get_vm_logs_by_hostname_success(client, api_token_headers, monkeypatch):
    """Test getting VM logs by hostname successfully."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_vm_by_hostname.return_value = {
        "hostname": "lablink-vm-test-1",
    }
    fake_db.get_vm_logs.return_value = {
        "cloud_init_logs": "Cloud init log data.",
        "docker_logs": "Docker log data.",
    }
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API
    resp = client.get(
        f"{VM_LOGS_ENDPOINT}/lablink-vm-test-1", headers=api_token_headers
    )

    assert resp.status_code == 200
    assert resp.is_json
    result = resp.get_json()
    assert result["hostname"] == "lablink-vm-test-1"
    assert result["cloud_init_logs"] == "Cloud init log data."
    assert result["docker_logs"] == "Docker log data."
    assert result["logs"] == "Cloud init log data.\nDocker log data."
    fake_db.get_vm_logs.assert_called_once_with(hostname="lablink-vm-test-1")


def test_vm_logs_by_hostname_not_found(client, api_token_headers, monkeypatch):
    """Test getting VM logs by hostname when not found."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_vm_by_hostname.return_value = None
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API
    resp = client.get(
        f"{VM_LOGS_ENDPOINT}/lablink-vm-test-1", headers=api_token_headers
    )

    assert resp.status_code == 404
    assert resp.is_json
    assert resp.get_json() == {"error": "VM not found."}
    fake_db.get_vm_logs.assert_not_called()


def test_vm_logs_by_hostname_installing_cloud_watch(
    client, api_token_headers, monkeypatch
):
    """Test getting VM logs by hostname when VM is initializing."""
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
    resp = client.get(
        f"{VM_LOGS_ENDPOINT}/lablink-vm-test-1", headers=api_token_headers
    )

    assert resp.status_code == 503
    assert resp.is_json
    assert resp.get_json() == {"error": "VM is initializing."}


def test_vm_logs_by_hostname_internal_error(client, api_token_headers, monkeypatch):
    """Test getting VM logs by hostname with internal error."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.get_vm_by_hostname.side_effect = Exception("Internal error")
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call the API
    resp = client.get(
        f"{VM_LOGS_ENDPOINT}/lablink-vm-test-1", headers=api_token_headers
    )

    assert resp.status_code == 500
    assert resp.is_json
    assert resp.get_json() == {"error": "Failed to get VM logs."}
    fake_db.get_vm_logs.assert_not_called()


def test_receive_vm_metrics_success(client, api_token_headers, monkeypatch):
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
    resp = client.post(
        f"{METRICS_ENDPOINT}/{hostname}", json=metrics_data, headers=api_token_headers
    )

    # Assert the response
    assert resp.status_code == 200
    assert resp.get_json() == {"message": "VM metrics posted successfully."}
    fake_db.vm_exists.assert_called_once_with(hostname=hostname)
    # Updated to use atomic method
    fake_db.update_vm_metrics_atomic.assert_called_once_with(
        hostname=hostname, metrics=metrics_data
    )


def test_receive_vm_metrics_vm_not_found(client, api_token_headers, monkeypatch):
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
    resp = client.post(
        f"{METRICS_ENDPOINT}/{hostname}", json=metrics_data, headers=api_token_headers
    )

    # Assert the response
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "VM not found."}
    fake_db.vm_exists.assert_called_once_with(hostname=hostname)
    fake_db.update_vm_metrics_atomic.assert_not_called()


def test_receive_vm_metrics_internal_error(client, api_token_headers, monkeypatch):
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
    resp = client.post(
        f"{METRICS_ENDPOINT}/{hostname}", json=metrics_data, headers=api_token_headers
    )

    # Assert the response
    assert resp.status_code == 500
    assert resp.get_json() == {"error": "Failed to post VM metrics."}
    fake_db.vm_exists.assert_called_once_with(hostname=hostname)
    fake_db.update_vm_metrics_atomic.assert_called_once_with(
        hostname=hostname, metrics=metrics_data
    )


def test_receive_vm_metrics_concurrent(client, api_token_headers, monkeypatch):
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
        return client.post(
            f"{METRICS_ENDPOINT}/{hostname}",
            json=metrics_data,
            headers=api_token_headers,
        )

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
    assert resp.status_code == 200
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
    assert resp.status_code == 200
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


# ──────────────────────────────────────────────────────────────────────
# Bearer token authentication tests
# ──────────────────────────────────────────────────────────────────────


# Endpoints that require ONLY API token auth (machine-to-machine)
TOKEN_PROTECTED_ENDPOINTS = [
    ("POST", VM_LOGS_ENDPOINT, {"log_group": "g", "log_stream": "s", "messages": ["m"]}),
    ("POST", f"{METRICS_ENDPOINT}/vm-1", {"cloud_init_duration_seconds": 120}),
]

# Endpoints that require a per-client secret (require_client_secret decorator)
CLIENT_SECRET_PROTECTED_ENDPOINTS = [
    ("POST", UPDATE_INUSE_STATUS_ENDPOINT, {"hostname": "vm-1", "status": True}),
    ("POST", UPDATE_GPU_HEALTH_ENDPOINT, {"hostname": "vm-1", "gpu_status": "Healthy"}),
    ("POST", HEARTBEAT_ENDPOINT, {"vm_id": "vm-1"}),
    ("POST", VM_STATUS_UPDATE_ENDPOINT, {"hostname": "vm-1", "status": "running"}),
]

# Endpoints that accept either session auth or API token (admin UI + VMs)
DUAL_AUTH_ENDPOINTS = [
    ("GET", VM_STATUS_UPDATE_ENDPOINT, None),
    ("GET", f"{VM_LOGS_ENDPOINT}/vm-1", None),
]


@pytest.mark.parametrize("method,endpoint,json_data", TOKEN_PROTECTED_ENDPOINTS)
def test_token_protected_endpoints_reject_no_token(
    client, monkeypatch, method, endpoint, json_data
):
    """All token-protected endpoints return 401 without a bearer token."""
    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    if method == "GET":
        resp = client.get(endpoint)
    else:
        resp = client.post(endpoint, json=json_data)

    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Missing or invalid Authorization header."


@pytest.mark.parametrize("method,endpoint,json_data", TOKEN_PROTECTED_ENDPOINTS)
def test_token_protected_endpoints_reject_wrong_token(
    client, monkeypatch, method, endpoint, json_data
):
    """All token-protected endpoints return 401 with an invalid bearer token."""
    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    bad_headers = {"Authorization": "Bearer wrong-token-value"}
    if method == "GET":
        resp = client.get(endpoint, headers=bad_headers)
    else:
        resp = client.post(endpoint, json=json_data, headers=bad_headers)

    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Invalid API token."


@pytest.mark.parametrize("method,endpoint,json_data", TOKEN_PROTECTED_ENDPOINTS)
def test_token_protected_endpoints_reject_non_bearer_auth(
    client, monkeypatch, method, endpoint, json_data
):
    """All token-protected endpoints reject non-Bearer auth schemes."""
    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    bad_headers = {"Authorization": "Basic dXNlcjpwYXNz"}
    if method == "GET":
        resp = client.get(endpoint, headers=bad_headers)
    else:
        resp = client.post(endpoint, json=json_data, headers=bad_headers)

    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Missing or invalid Authorization header."


@pytest.mark.parametrize("method,endpoint,json_data", CLIENT_SECRET_PROTECTED_ENDPOINTS)
def test_client_secret_endpoints_reject_no_token(
    client, monkeypatch, method, endpoint, json_data
):
    """All client-secret-protected endpoints return 401 without a bearer token."""
    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    if method == "GET":
        resp = client.get(endpoint)
    else:
        resp = client.post(endpoint, json=json_data)

    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Missing or invalid Authorization header."


@pytest.mark.parametrize("method,endpoint,json_data", CLIENT_SECRET_PROTECTED_ENDPOINTS)
def test_client_secret_endpoints_reject_wrong_secret(
    client, monkeypatch, method, endpoint, json_data
):
    """All client-secret-protected endpoints return 401 with an invalid secret."""
    fake_db = MagicMock()
    _stub_client_secret(fake_db)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    bad_headers = {"Authorization": "Bearer wrong-secret-value"}
    if method == "GET":
        resp = client.get(endpoint, headers=bad_headers)
    else:
        resp = client.post(endpoint, json=json_data, headers=bad_headers)

    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Invalid client secret."


@pytest.mark.parametrize("method,endpoint,json_data", CLIENT_SECRET_PROTECTED_ENDPOINTS)
def test_client_secret_endpoints_reject_non_bearer_auth(
    client, monkeypatch, method, endpoint, json_data
):
    """All client-secret-protected endpoints reject non-Bearer auth schemes."""
    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    bad_headers = {"Authorization": "Basic dXNlcjpwYXNz"}
    if method == "GET":
        resp = client.get(endpoint, headers=bad_headers)
    else:
        resp = client.post(endpoint, json=json_data, headers=bad_headers)

    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Missing or invalid Authorization header."


@pytest.mark.parametrize("method,endpoint,json_data", DUAL_AUTH_ENDPOINTS)
def test_dual_auth_endpoints_reject_no_auth(
    client, monkeypatch, method, endpoint, json_data
):
    """Dual-auth endpoints return 401 without any authentication."""
    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    if method == "GET":
        resp = client.get(endpoint)
    else:
        resp = client.post(endpoint, json=json_data)

    assert resp.status_code == 401


@pytest.mark.parametrize("method,endpoint,json_data", DUAL_AUTH_ENDPOINTS)
def test_dual_auth_endpoints_reject_wrong_token(
    client, monkeypatch, method, endpoint, json_data
):
    """Dual-auth endpoints return 401 with an invalid bearer token."""
    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    bad_headers = {"Authorization": "Bearer wrong-token-value"}
    if method == "GET":
        resp = client.get(endpoint, headers=bad_headers)
    else:
        resp = client.post(endpoint, json=json_data, headers=bad_headers)

    assert resp.status_code == 401
    assert resp.get_json()["error"] == "Invalid API token."


@pytest.mark.parametrize("method,endpoint,json_data", DUAL_AUTH_ENDPOINTS)
def test_dual_auth_endpoints_accept_api_token(
    client, api_token_headers, monkeypatch, method, endpoint, json_data
):
    """Dual-auth endpoints accept a valid API bearer token."""
    fake_db = MagicMock()
    fake_db.get_unassigned_vms.return_value = []
    fake_db.get_all_vm_status.return_value = {"vm-1": "running"}
    fake_db.get_vm_by_hostname.return_value = {"hostname": "vm-1", "status": "running"}
    fake_db.get_vm_logs.return_value = {
        "cloud_init_logs": "log",
        "docker_logs": None,
    }
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    if method == "GET":
        resp = client.get(endpoint, headers=api_token_headers)
    else:
        resp = client.post(endpoint, json=json_data, headers=api_token_headers)

    assert resp.status_code == 200


def test_request_vm_does_not_require_token(client, monkeypatch):
    """The student-facing /api/request_vm endpoint does NOT require a bearer token."""
    fake_db = MagicMock()
    # Empty pool -> ValueError -> 503 no_seats page (still NOT 401).
    fake_db.get_assigned_vm_for_email.return_value = None
    fake_db.assign_vm.side_effect = ValueError("No available VMs to assign.")
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    # Call without any auth header
    data = {"email": "user@example.com"}
    resp = client.post(REQUEST_VM_ENDPOINT, data=data)

    # Should NOT return 401 - this endpoint is public.
    assert resp.status_code != 401


# -- Heartbeat endpoint --------------------------------------------------

def _heartbeat_payload(**overrides):
    base = {
        "vm_id": "test-vm-dev-1",
        "boot_id": "bid-abc",
        "timestamp": "2026-04-20T12:00:00+00:00",
        "disk_free_pct": 80,
    }
    base.update(overrides)
    return base


def test_heartbeat_success(client, monkeypatch):
    """Valid heartbeat payload returns 200 and calls record_heartbeat."""
    fake_db = MagicMock()
    fake_db.record_heartbeat.return_value = True
    _stub_client_secret(fake_db)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.post(
        HEARTBEAT_ENDPOINT,
        json=_heartbeat_payload(),
        headers=_CLIENT_SECRET_HEADERS,
    )

    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    fake_db.record_heartbeat.assert_called_once_with(
        hostname="test-vm-dev-1",
        boot_id="bid-abc",
        disk_free_pct=80,
    )


def test_heartbeat_rejects_missing_token(client, monkeypatch):
    """Heartbeat endpoint requires API token."""
    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.post(HEARTBEAT_ENDPOINT, json=_heartbeat_payload())

    assert resp.status_code == 401
    fake_db.record_heartbeat.assert_not_called()


def test_heartbeat_rejects_missing_vm_id(client, monkeypatch):
    """Missing vm_id — decorator rejects with 401 (no identity)."""
    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    payload = _heartbeat_payload()
    payload.pop("vm_id")
    resp = client.post(HEARTBEAT_ENDPOINT, json=payload, headers=_CLIENT_SECRET_HEADERS)

    assert resp.status_code == 401
    fake_db.record_heartbeat.assert_not_called()


def test_heartbeat_unknown_hostname_returns_404(
    client, monkeypatch
):
    """record_heartbeat returning False surfaces as 404."""
    fake_db = MagicMock()
    fake_db.record_heartbeat.return_value = False
    _stub_client_secret(fake_db)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.post(
        HEARTBEAT_ENDPOINT,
        json=_heartbeat_payload(vm_id="ghost"),
        headers=_CLIENT_SECRET_HEADERS,
    )

    assert resp.status_code == 404


def test_heartbeat_db_error_returns_500(client, monkeypatch):
    """Unexpected exceptions surface as 500."""
    fake_db = MagicMock()
    fake_db.record_heartbeat.side_effect = Exception("boom")
    _stub_client_secret(fake_db)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.post(
        HEARTBEAT_ENDPOINT,
        json=_heartbeat_payload(),
        headers=_CLIENT_SECRET_HEADERS,
    )

    assert resp.status_code == 500


def test_heartbeat_accepts_null_health_fields(
    client, monkeypatch
):
    """Partial sampler failure (null booleans) must still be accepted.

    The client sets a field to None when its probe fails; we want the
    row updated with whatever was reported rather than rejecting the
    whole heartbeat.
    """
    fake_db = MagicMock()
    fake_db.record_heartbeat.return_value = True
    _stub_client_secret(fake_db)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    payload = _heartbeat_payload(disk_free_pct=None)
    resp = client.post(HEARTBEAT_ENDPOINT, json=payload, headers=_CLIENT_SECRET_HEADERS)

    assert resp.status_code == 200
    call = fake_db.record_heartbeat.call_args
    assert call.kwargs["disk_free_pct"] is None


# -- Cross-endpoint last_seen_at refresh --------------------------------

def test_gpu_health_bumps_last_seen(client, monkeypatch):
    """POST /api/gpu_health refreshes last_seen_at for the VM."""
    fake_db = MagicMock()
    _stub_client_secret(fake_db)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.post(
        UPDATE_GPU_HEALTH_ENDPOINT,
        json={"hostname": "vm-1", "gpu_status": "Healthy"},
        headers=_CLIENT_SECRET_HEADERS,
    )

    assert resp.status_code == 200
    fake_db.touch_last_seen.assert_called_once_with(hostname="vm-1")


def test_vm_status_bumps_last_seen(client, monkeypatch):
    """POST /api/vm-status refreshes last_seen_at for the VM."""
    fake_db = MagicMock()
    _stub_client_secret(fake_db)
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.post(
        VM_STATUS_UPDATE_ENDPOINT,
        json={"hostname": "vm-1", "status": "running"},
        headers=_CLIENT_SECRET_HEADERS,
    )

    assert resp.status_code == 200
    fake_db.touch_last_seen.assert_called_once_with(hostname="vm-1")


def test_vm_metrics_bumps_last_seen(client, api_token_headers, monkeypatch):
    """POST /api/vm-metrics/<hostname> refreshes last_seen_at."""
    fake_db = MagicMock()
    fake_db.vm_exists.return_value = True
    monkeypatch.setattr(
        "lablink_allocator_service.main.database", fake_db, raising=False
    )

    resp = client.post(
        f"{METRICS_ENDPOINT}/vm-1",
        json={"container_start": 0, "container_end": 1},
        headers=api_token_headers,
    )

    assert resp.status_code == 200
    fake_db.touch_last_seen.assert_called_once_with(hostname="vm-1")
