"""The allocator's own log endpoint and admin page."""


def test_api_requires_auth(client):
    assert client.get("/api/allocator-logs").status_code == 401


def test_page_requires_auth(client):
    assert client.get("/admin/allocator-logs").status_code == 401


def test_api_returns_logs(client, admin_headers, monkeypatch):
    monkeypatch.setattr(
        "lablink_allocator_service.routes.allocator_logs.read_allocator_log",
        lambda: "Starting nginx on :5000...",
    )
    body = client.get("/api/allocator-logs", headers=admin_headers).get_json()
    assert body["docker_logs"] == "Starting nginx on :5000..."
    assert body["cloud_init_logs"] is None
    assert body["error"] is None


def test_api_explains_a_missing_log_file(client, admin_headers, monkeypatch):
    """A missing file is a user-facing explanation, not a 500."""
    monkeypatch.setattr(
        "lablink_allocator_service.routes.allocator_logs.read_allocator_log",
        lambda: None,
    )
    resp = client.get("/api/allocator-logs", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["docker_logs"] is None
    assert "lablink logs" in body["error"]


def test_page_renders_single_docker_tab(client, admin_headers):
    """Cloud-init is out of scope for the allocator, so only one tab."""
    html = client.get(
        "/admin/allocator-logs", headers=admin_headers
    ).data.decode()
    assert "Allocator Logs" in html
    assert 'id="cloudInitTab"' not in html
    assert 'id="dockerTab"' in html
    assert 'id="dockerLogBox"' in html
    assert '"/api/allocator-logs"' in html


def test_admin_dashboard_links_to_the_page(client, admin_headers):
    html = client.get("/admin", headers=admin_headers).data.decode()
    assert "/admin/allocator-logs" in html
