"""Tests for /api/request_vm reassignment branching.

Covers the cases of the request-flow change in PR 1:
1. Email has no existing assignment -> fresh assignment (regression).
2. Email has an existing running VM -> reassign_crd, success page.
3. Email has an existing rebooting/initializing VM -> reassign_crd,
   recovery page.
4. Email has an existing error VM -> retry-shortly message.
5. Reassign race -> reassign_crd returns False -> retry page.
6. Unknown status -> fall through to fresh assignment.
"""

from unittest.mock import MagicMock


REQUEST_VM_ENDPOINT = "/api/request_vm"

VALID_CRD_COMMAND = (
    "DISPLAY= /opt/google/chrome-remote-desktop/start-host "
    "--code='4/abc123' --redirect-url='https://example.com' "
    "--name='vm-1'"
)


def test_request_vm_existing_running_reassigns_same_host(
    client, monkeypatch
):
    """Email already owns a running VM: reassign CRD on same host."""
    from lablink_allocator_service import main

    fake_db = MagicMock()
    fake_db.get_assigned_vm_for_email.return_value = {
        "hostname": "vm-7",
        "status": "running",
        "reboot_count": 0,
    }
    fake_db.reassign_crd.return_value = True
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    resp = client.post(
        REQUEST_VM_ENDPOINT,
        data={
            "email": "student@test.edu",
            "crd_command": VALID_CRD_COMMAND,
        },
    )

    assert resp.status_code == 200
    # Conditional UPDATE carries expected_email for optimistic concurrency
    fake_db.reassign_crd.assert_called_once_with(
        hostname="vm-7",
        crd_command=VALID_CRD_COMMAND,
        pin=main.PIN,
        expected_email="student@test.edu",
    )
    # Fresh assignment path is NOT taken
    fake_db.assign_vm.assert_not_called()
    fake_db.get_unassigned_vms.assert_not_called()
    # Response body mentions the hostname
    assert b"vm-7" in resp.data


def test_request_vm_existing_rebooting_renders_recovery_page(
    client, monkeypatch
):
    """Email's VM is mid-reboot: queue CRD, render recovery page."""
    from lablink_allocator_service import main

    fake_db = MagicMock()
    fake_db.get_assigned_vm_for_email.return_value = {
        "hostname": "vm-3",
        "status": "rebooting",
        "reboot_count": 1,
    }
    fake_db.reassign_crd.return_value = True
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    resp = client.post(
        REQUEST_VM_ENDPOINT,
        data={
            "email": "student@test.edu",
            "crd_command": VALID_CRD_COMMAND,
        },
    )

    assert resp.status_code == 200
    fake_db.reassign_crd.assert_called_once()
    fake_db.assign_vm.assert_not_called()
    # Recovery page mentions the hostname
    assert b"vm-3" in resp.data
    assert b"Recovering" in resp.data


def test_request_vm_reassign_race_renders_retry_message(
    client, monkeypatch
):
    """reassign_crd returning False (race) renders a retry-page.

    Simulates the race where auto-reboot's release_assignment fires
    between get_assigned_vm_for_email and reassign_crd. The UPDATE's
    useremail guard fails, reassign_crd returns False, the handler
    asks the student to retry instead of rendering a misleading
    success page.
    """
    from lablink_allocator_service import main

    fake_db = MagicMock()
    fake_db.get_assigned_vm_for_email.return_value = {
        "hostname": "vm-7",
        "status": "running",
        "reboot_count": 0,
    }
    fake_db.reassign_crd.return_value = False  # race loss
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    resp = client.post(
        REQUEST_VM_ENDPOINT,
        data={
            "email": "student@test.edu",
            "crd_command": VALID_CRD_COMMAND,
        },
    )

    assert resp.status_code == 200
    fake_db.reassign_crd.assert_called_once()
    # Not falsely presented as success
    assert b"VM Assigned Successfully" not in resp.data
    # Retry guidance surfaced to the student
    assert b"try again" in resp.data.lower()
    # Fresh assignment NOT auto-triggered (student must retry explicitly)
    fake_db.assign_vm.assert_not_called()


def test_request_vm_existing_error_renders_retry_message(
    client, monkeypatch
):
    """Email's VM is in error state: do not reassign; ask to retry."""
    from lablink_allocator_service import main

    fake_db = MagicMock()
    fake_db.get_assigned_vm_for_email.return_value = {
        "hostname": "vm-9",
        "status": "error",
        "reboot_count": 3,
    }
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    resp = client.post(
        REQUEST_VM_ENDPOINT,
        data={
            "email": "student@test.edu",
            "crd_command": VALID_CRD_COMMAND,
        },
    )

    assert resp.status_code == 200
    fake_db.reassign_crd.assert_not_called()
    fake_db.assign_vm.assert_not_called()
    assert b"try again" in resp.data.lower()


def test_request_vm_no_existing_assignment_picks_fresh_vm(
    client, monkeypatch
):
    """Regression: email with no VM gets a fresh assignment."""
    from lablink_allocator_service import main

    fake_db = MagicMock()
    fake_db.get_assigned_vm_for_email.return_value = None
    fake_db.get_unassigned_vms.return_value = ["vm-free-1"]
    fake_db.get_vm_details.return_value = ["vm-free-1", "123456", "cmd"]
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    resp = client.post(
        REQUEST_VM_ENDPOINT,
        data={
            "email": "new@test.edu",
            "crd_command": VALID_CRD_COMMAND,
        },
    )

    assert resp.status_code == 200
    fake_db.assign_vm.assert_called_once()
    fake_db.reassign_crd.assert_not_called()
    assert b"vm-free-1" in resp.data


def test_request_vm_unexpected_status_falls_through_to_fresh_assignment(
    client, monkeypatch
):
    """Unknown status on existing row falls through to fresh assignment."""
    from lablink_allocator_service import main

    fake_db = MagicMock()
    fake_db.get_assigned_vm_for_email.return_value = {
        "hostname": "vm-unknown-state",
        "status": "stopped",  # not handled explicitly
        "reboot_count": 0,
    }
    fake_db.get_unassigned_vms.return_value = ["vm-free-2"]
    fake_db.get_vm_details.return_value = ["vm-free-2", "123456", "cmd"]
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    resp = client.post(
        REQUEST_VM_ENDPOINT,
        data={
            "email": "student@test.edu",
            "crd_command": VALID_CRD_COMMAND,
        },
    )

    assert resp.status_code == 200
    # Fell through to fresh-assignment path
    fake_db.reassign_crd.assert_not_called()
    fake_db.assign_vm.assert_called_once()
    assert b"vm-free-2" in resp.data
