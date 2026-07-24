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
    assert b'href="/admin"' in response.data
    assert "Back to Admin Dashboard".encode() in response.data


def test_admin_delete_instance_no_auth(client):
    """Test deleting an instance without authentication."""
    response = client.get("/admin/instances/delete")
    assert response.status_code == 401


def test_admin_create_instance(client, admin_headers):
    """Test the create-instances page as an admin."""
    response = client.get("/admin/create", headers=admin_headers)
    assert response.status_code == 200
    assert b"Launch VMs" in response.data
    assert b'href="/admin"' in response.data
    assert "Back to Admin Dashboard".encode() in response.data


def test_admin_create_instance_no_auth(client):
    """Test the create-instances page without authentication."""
    response = client.get("/admin/create")
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
def test_view_instances_shows_back_to_admin_link(mock_database, client, admin_headers):
    mock_database.get_all_vms.return_value = []

    resp = client.get("/admin/instances", headers=admin_headers)

    html = resp.data.decode()
    assert 'href="/admin"' in html
    assert "Back to Admin Dashboard" in html


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


@patch("lablink_allocator_service.main.database")
def test_instances_html_escapes_operation_output_and_error(
    mock_database, client, admin_headers,
):
    """op.output/op.error (terraform stdout/stderr) must be HTML-escaped
    before going into innerHTML, not interpolated raw — XSS risk otherwise."""
    mock_database.get_all_vms.return_value = []

    resp = client.get("/admin/instances", headers=admin_headers)
    html = resp.data.decode()

    assert "function escapeHtml(" in html
    assert "${escapeHtml(op.output)}" in html
    assert "${escapeHtml(op.error)}" in html
    assert "${op.output}" not in html
    assert "${op.error}" not in html


@patch("lablink_allocator_service.main.database")
def test_view_instances_shows_error_banner(mock_database, client, admin_headers):
    mock_database.get_all_vms.return_value = []

    resp = client.get(
        "/admin/instances?error=num_vms_required", headers=admin_headers
    )

    assert b"Number of VMs is required." in resp.data


@patch("lablink_allocator_service.main.database")
def test_view_instances_error_banner_includes_job_id(mock_database, client, admin_headers):
    mock_database.get_all_vms.return_value = []

    resp = client.get(
        "/admin/instances?error=already_in_progress&job_id=7", headers=admin_headers
    )

    assert b"job #7" in resp.data


@patch("lablink_allocator_service.main.database")
def test_view_instances_scrubs_error_params_from_url(mock_database, client, admin_headers):
    """Both `error` and `vnc_error` are stripped from the address bar via
    history.replaceState after being shown once, so a raw page refresh
    does not keep re-displaying a stale message (a bug confirmed present
    for vnc_error before this change)."""
    mock_database.get_all_vms.return_value = []

    resp = client.get("/admin/instances", headers=admin_headers)
    html = resp.data.decode()

    assert "history.replaceState" in html
    assert "vnc_error" in html
    assert "'error'" in html or '"error"' in html


def test_instances_fragment_requires_auth(client):
    resp = client.get("/admin/instances/fragment")
    assert resp.status_code == 401


@patch("lablink_allocator_service.main.database")
def test_instances_fragment_renders_vm_rows(mock_database, client, admin_headers):
    mock_database.get_all_vms.return_value = [
        SimpleNamespace(
            hostname="vm-1", useremail="a@x.com", inuse=False,
            healthy="Healthy", status="running", sessionid=None,
            adminreservedat=None, containerstartupdurationseconds=1.0,
            totalstartupdurationseconds=2.0,
        ),
    ]

    resp = client.get("/admin/instances/fragment", headers=admin_headers)

    assert resp.status_code == 200
    html = resp.data.decode()
    assert "vm-1" in html
    assert "<!DOCTYPE html>" not in html
    assert "Back to Admin Dashboard" not in html


@patch("lablink_allocator_service.main.database")
def test_instances_fragment_shares_action_logic_with_full_page(
    mock_database, client, admin_headers,
):
    """The fragment endpoint must produce the same Peek/Connect/Release
    markup as the full page for the same VM state, proving both call the
    same vm_actions macro instead of two independently maintained
    conditionals."""
    mock_database.get_all_vms.return_value = [
        SimpleNamespace(
            hostname="vm-connect", useremail=None, inuse=False,
            healthy="Healthy", status="running", sessionid=None,
            adminreservedat=None, containerstartupdurationseconds=0,
            totalstartupdurationseconds=0,
        ),
    ]

    full_html = client.get("/admin/instances", headers=admin_headers).data.decode()
    fragment_html = client.get(
        "/admin/instances/fragment", headers=admin_headers
    ).data.decode()

    assert "/admin/instances/vm-connect/connect" in full_html
    assert "/admin/instances/vm-connect/connect" in fragment_html


@patch("lablink_allocator_service.main.database")
def test_view_instances_renders_card_view_container(mock_database, client, admin_headers):
    mock_database.get_all_vms.return_value = [
        SimpleNamespace(
            hostname="vm-1", useremail=None, inuse=False, healthy="Healthy",
            status="running", sessionid=None, adminreservedat=None,
            containerstartupdurationseconds=0, totalstartupdurationseconds=0,
        ),
    ]
    resp = client.get("/admin/instances", headers=admin_headers)
    html = resp.data.decode()

    assert 'id="vm-card-container"' in html
    assert 'class="vm-card"' in html
    assert "vm-1" in html
    assert "RUNNING" in html


@patch("lablink_allocator_service.main.database")
def test_view_instances_card_view_has_full_action_parity(mock_database, client, admin_headers):
    """Card view must offer the same Connect action as the table for an
    unclaimed running VM — full parity, not a read-only status board."""
    mock_database.get_all_vms.return_value = [
        SimpleNamespace(
            hostname="vm-connect", useremail=None, inuse=False, healthy="Healthy",
            status="running", sessionid=None, adminreservedat=None,
            containerstartupdurationseconds=0, totalstartupdurationseconds=0,
        ),
    ]
    resp = client.get("/admin/instances", headers=admin_headers)
    html = resp.data.decode()

    # Appears twice: once in the table's actions cell, once in the card's.
    assert html.count("/admin/instances/vm-connect/connect") == 2


@patch("lablink_allocator_service.main.database")
def test_view_instances_card_view_shows_summary_stats(mock_database, client, admin_headers):
    """The retired dashboard template's most visually distinctive element —
    a Running/Initializing/Errors/Total counts row above the card grid —
    computed server-side from the same instances list, no new backend
    call."""
    mock_database.get_all_vms.return_value = [
        SimpleNamespace(
            hostname="vm-running", useremail=None, inuse=False, healthy="Healthy",
            status="running", sessionid=None, adminreservedat=None,
            containerstartupdurationseconds=0, totalstartupdurationseconds=0,
        ),
        SimpleNamespace(
            hostname="vm-error", useremail=None, inuse=False, healthy="Unhealthy",
            status="error", sessionid=None, adminreservedat=None,
            containerstartupdurationseconds=0, totalstartupdurationseconds=0,
        ),
        SimpleNamespace(
            hostname="vm-provisioning", useremail=None, inuse=False, healthy=None,
            status="provisioning", sessionid=None, adminreservedat=None,
            containerstartupdurationseconds=0, totalstartupdurationseconds=0,
        ),
    ]
    resp = client.get("/admin/instances", headers=admin_headers)
    html = resp.data.decode()

    assert 'class="vm-summary-row"' in html
    assert "Running" in html
    assert "Initializing" in html
    assert "Errors" in html
    assert "Total VMs" in html
    # 1 running, 1 error, 1 other (provisioning -> counted as "initializing"
    # bucket), 3 total.
    assert '<div class="vm-summary-count vm-summary-running">1</div>' in html
    assert '<div class="vm-summary-count vm-summary-error">1</div>' in html
    assert '<div class="vm-summary-count vm-summary-initializing">1</div>' in html
    assert '<div class="vm-summary-count vm-summary-total">3</div>' in html


def test_view_instances_has_view_toggle_buttons(client, admin_headers):
    resp = client.get("/admin/instances", headers=admin_headers)
    html = resp.data.decode()
    assert 'id="view-table-btn"' in html
    assert 'id="view-card-btn"' in html
    assert "localStorage" in html
