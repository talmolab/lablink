from unittest.mock import MagicMock, patch
from types import SimpleNamespace


def test_home_basic_structure(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.data.decode()

    # Title
    assert "<title>LabLink Allocator</title>" in html

    # Heading text
    assert "Welcome to LabLink!" in html

    # VM count placeholder
    assert 'id="vms_available"' in html
    assert 'id="unassigned_vms_count"' in html

    # Form basics
    assert '<form action="/api/request_vm" method="post">' in html
    assert 'name="email"' in html


def test_admin_instances_no_auth(client):
    """Test the admin instances endpoint without authentication."""
    response = client.get("/admin/instances")
    assert response.status_code == 401


def test_byo_onboarding_no_auth(client):
    """BYO onboarding page leaks the live register_token, so it must be
    behind admin auth like the rest of /admin."""
    response = client.get("/admin/byo-onboarding")
    assert response.status_code == 401


def test_byo_onboarding_renders_register_command(client, admin_headers):
    """Page renders a ready-to-copy `lablink client register` command with the
    current allocator URL and live REGISTER_TOKEN. The admin should be
    able to copy it verbatim and hand it to a BYO operator."""
    from lablink_allocator_service import main
    response = client.get("/admin/byo-onboarding", headers=admin_headers)
    assert response.status_code == 200
    html = response.data.decode()
    assert "lablink client register" in html
    assert "--allocator-url" in html
    assert "--register-token" in html
    # Live token (not its hash) is rendered for copy-paste.
    assert main.REGISTER_TOKEN in html


def test_byo_onboarding_hides_insecure_for_letsencrypt(client, admin_headers, monkeypatch):
    """`--insecure` only renders when ssl.provider is self_signed; for
    letsencrypt or no-SSL deployments, the flag would be a footgun."""
    from lablink_allocator_service import main
    monkeypatch.setattr(main.cfg.ssl, "provider", "letsencrypt", raising=False)
    response = client.get("/admin/byo-onboarding", headers=admin_headers)
    html = response.data.decode()
    assert "--insecure" not in html


def test_byo_onboarding_shows_insecure_for_self_signed(client, admin_headers, monkeypatch):
    from lablink_allocator_service import main
    monkeypatch.setattr(main.cfg.ssl, "provider", "self_signed", raising=False)
    response = client.get("/admin/byo-onboarding", headers=admin_headers)
    html = response.data.decode()
    assert "--insecure" in html


@patch("lablink_allocator_service.main.database")
def test_admin_instances(mock_database, client, admin_headers):
    """Test the admin instances endpoint without any instances."""
    mock_database.get_all_vms.return_value = []
    response = client.get("/admin/instances", headers=admin_headers)
    assert response.status_code == 200


@patch("lablink_allocator_service.main.database")
def test_view_instances_with_rows(mock_database, client, admin_headers):
    """Test the admin instances endpoint with rows."""
    rows = [
        SimpleNamespace(
            hostname="vm-1",
            useremail="a@x.com",
            inuse=False,
            healthy="Unhealthy",
        ),
        SimpleNamespace(
            hostname="vm-2",
            useremail="b@y.com",
            inuse=True,
            healthy="Healthy",
        ),
    ]
    mock_database.get_all_vms.return_value = rows

    resp = client.get("/admin/instances", headers=admin_headers)
    assert resp.status_code == 200
    assert b"vm-1" in resp.data
    assert b"vm-2" in resp.data


def test_admin_delete_instance(client, admin_headers):
    """Test deleting an instance as an admin."""
    response = client.get("/admin/instances/delete", headers=admin_headers)
    assert response.status_code == 200
    assert b"Run terraform destroy" in response.data


def test_admin_delete_instance_no_auth(client):
    """Test deleting an instance without authentication."""
    response = client.get("/admin/instances/delete")
    assert response.status_code == 401


def test_log_page_no_auth(client):
    """Test the log page without authentication."""
    hostname = "test-vm-dev-1"
    response = client.get(f"/admin/logs/{hostname}")
    assert response.status_code == 401


def test_log_page_success(client, admin_headers, monkeypatch):
    """Test the log page with authentication."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.vm_exists.return_value = True
    monkeypatch.setattr("lablink_allocator_service.main.database", fake_db)

    hostname = "test-vm-dev-1"
    response = client.get(f"/admin/logs/{hostname}", headers=admin_headers)
    assert response.status_code == 200
    assert f"VM Logs - {hostname}" in response.data.decode()
    fake_db.vm_exists.assert_called_once_with(hostname=hostname)


def test_log_page_vm_not_found(client, admin_headers, monkeypatch):
    """Test the log page with a non-existent VM."""
    # Mock the database
    fake_db = MagicMock()
    fake_db.vm_exists.return_value = False
    monkeypatch.setattr("lablink_allocator_service.main.database", fake_db)

    hostname = "test-vm-dev-1"
    response = client.get(f"/admin/logs/{hostname}", headers=admin_headers)
    assert response.status_code == 404
    assert "VM not found." in response.data.decode()


@patch("lablink_allocator_service.main.database")
def test_view_instances_vnc_actions_by_state(mock_database, client, admin_headers):
    """Each VM state shows the right VNC action in the actions cell."""
    rows = [
        SimpleNamespace(
            hostname="vm-peek", useremail="a@x.com", inuse=True,
            healthy="Healthy", status="running", sessionid="sid-1",
            adminreservedat=None,
        ),
        SimpleNamespace(
            hostname="vm-connect", useremail=None, inuse=False,
            healthy="Healthy", status="running", sessionid=None,
            adminreservedat=None,
        ),
        SimpleNamespace(
            hostname="vm-admin-active", useremail=None, inuse=False,
            healthy="Healthy", status="running", sessionid=None,
            adminreservedat="2026-07-17T12:00:00Z",
        ),
        SimpleNamespace(
            hostname="vm-provisioning", useremail=None, inuse=False,
            healthy=None, status="provisioning", sessionid=None,
            adminreservedat=None,
        ),
    ]
    mock_database.get_all_vms.return_value = rows

    resp = client.get("/admin/instances", headers=admin_headers)
    html = resp.data.decode()

    assert "/admin/instances/vm-peek/peek" in html
    assert "/admin/instances/vm-connect/connect" in html
    assert "/admin/instances/vm-admin-active/release" in html
    assert "Admin session active" in html
    assert "/admin/instances/vm-provisioning/connect" not in html
    assert "/admin/instances/vm-provisioning/peek" not in html


def test_view_instances_shows_vnc_error_banner(client, admin_headers):
    resp = client.get(
        "/admin/instances?vnc_error=connect_raced", headers=admin_headers
    )
    assert b"claimed by someone else" in resp.data


@patch("lablink_allocator_service.main.database")
def test_view_instances_embeds_job_id_from_query_param(
    mock_database, client, admin_headers,
):
    mock_database.get_all_vms.return_value = []

    resp = client.get("/admin/instances?job=17", headers=admin_headers)

    html = resp.data.decode()
    assert 'id="operation-banner"' in html
    assert "17" in html


@patch("lablink_allocator_service.main.database")
def test_view_instances_banner_absent_without_job_param(
    mock_database, client, admin_headers,
):
    """No ?job= param and nothing in progress: the banner container exists
    (for JS to fill in later) but starts with no job id embedded."""
    mock_database.get_all_vms.return_value = []

    resp = client.get("/admin/instances", headers=admin_headers)

    html = resp.data.decode()
    assert 'id="operation-banner"' in html
    assert 'const initialJobId = "";' in html
