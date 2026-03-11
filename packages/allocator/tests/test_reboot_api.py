"""Tests for reboot API endpoints."""

from unittest.mock import MagicMock

REBOOT_VM_ENDPOINT = "/api/reboot-vm"
REBOOT_INFO_ENDPOINT = "/api/reboot-vm"


def test_reboot_vm_success(client, admin_headers, monkeypatch):
    """Test manual reboot of a VM."""
    from lablink_allocator_service import main

    fake_db = MagicMock()
    fake_db.vm_exists.return_value = True
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    mock_reboot_service = MagicMock()
    mock_reboot_service._reboot_vm.return_value = True
    monkeypatch.setattr(main, "reboot_service", mock_reboot_service, raising=False)

    resp = client.post(
        REBOOT_VM_ENDPOINT,
        json={"hostname": "test-vm-1"},
        headers=admin_headers,
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert "Reboot initiated" in data["message"]
    mock_reboot_service._reboot_vm.assert_called_once_with("test-vm-1")


def test_reboot_vm_failure(client, admin_headers, monkeypatch):
    """Test reboot when reboot service fails."""
    from lablink_allocator_service import main

    fake_db = MagicMock()
    fake_db.vm_exists.return_value = True
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    mock_reboot_service = MagicMock()
    mock_reboot_service._reboot_vm.return_value = False
    monkeypatch.setattr(main, "reboot_service", mock_reboot_service, raising=False)

    resp = client.post(
        REBOOT_VM_ENDPOINT,
        json={"hostname": "test-vm-1"},
        headers=admin_headers,
    )

    assert resp.status_code == 500


def test_reboot_vm_missing_hostname(client, admin_headers):
    """Test reboot without hostname."""
    resp = client.post(
        REBOOT_VM_ENDPOINT,
        json={},
        headers=admin_headers,
    )
    assert resp.status_code == 400


def test_reboot_vm_not_found(client, admin_headers, monkeypatch):
    """Test reboot of non-existent VM."""
    from lablink_allocator_service import main

    fake_db = MagicMock()
    fake_db.vm_exists.return_value = False
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    resp = client.post(
        REBOOT_VM_ENDPOINT,
        json={"hostname": "nonexistent-vm"},
        headers=admin_headers,
    )
    assert resp.status_code == 404


def test_reboot_vm_requires_auth(client):
    """Test that reboot endpoint requires authentication."""
    resp = client.post(
        REBOOT_VM_ENDPOINT,
        json={"hostname": "test-vm-1"},
    )
    assert resp.status_code == 401


def test_get_reboot_info_success(client, admin_headers, monkeypatch):
    """Test getting reboot info for a VM."""
    from lablink_allocator_service import main

    fake_db = MagicMock()
    fake_db.vm_exists.return_value = True
    fake_db.get_reboot_info.return_value = {
        "reboot_count": 2,
        "last_reboot_time": None,
    }
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    resp = client.get(
        f"{REBOOT_INFO_ENDPOINT}/test-vm-1",
        headers=admin_headers,
    )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["hostname"] == "test-vm-1"
    assert data["reboot_count"] == 2


def test_get_reboot_info_vm_not_found(client, admin_headers, monkeypatch):
    """Test getting reboot info for non-existent VM."""
    from lablink_allocator_service import main

    fake_db = MagicMock()
    fake_db.vm_exists.return_value = False
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    resp = client.get(
        f"{REBOOT_INFO_ENDPOINT}/nonexistent-vm",
        headers=admin_headers,
    )

    assert resp.status_code == 404
