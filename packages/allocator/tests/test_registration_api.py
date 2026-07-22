"""Tests for the registration API + register-token at-rest hashing."""
import pytest
from unittest.mock import MagicMock


def test_register_token_global_exists():
    from lablink_allocator_service import main
    assert isinstance(main.REGISTER_TOKEN, str)
    assert len(main.REGISTER_TOKEN) >= 32


def test_init_database_upserts_register_token_hash(monkeypatch, omega_config):
    monkeypatch.setattr(
        "lablink_allocator_service.get_config.get_config",
        lambda: omega_config, raising=True,
    )
    from lablink_allocator_service import main
    monkeypatch.setattr(main, "cfg", omega_config, raising=False)

    fake_db = MagicMock()
    monkeypatch.setattr(
        "lablink_allocator_service.main.PostgresqlDatabase",
        lambda **kw: fake_db, raising=True,
    )
    main.init_database()

    fake_db.set_setting.assert_called_once()
    args = fake_db.set_setting.call_args[0]
    assert args[0] == "register_token_hash"
    assert args[1].startswith("$argon2")
    assert args[1] != main.REGISTER_TOKEN


def _decorated(monkeypatch, secret_hash_value, header):
    from lablink_allocator_service import main
    from flask import jsonify

    fake_db = MagicMock()
    fake_db.get_client_secret_hash.return_value = secret_hash_value
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    @main.require_client_secret
    def view():
        return jsonify(ok=True), 200

    with main.app.test_request_context(
        "/api/heartbeat", method="POST",
        json={"vm_id": "vm-1"},
        headers=({"Authorization": header} if header else {}),
    ):
        return view()


def test_require_client_secret_accepts_valid(monkeypatch):
    from lablink_allocator_service.secret_hash import hash_secret
    h = hash_secret("sek")
    resp = _decorated(monkeypatch, h, "Bearer sek")
    assert resp[1] == 200


def test_require_client_secret_rejects_wrong(monkeypatch):
    from lablink_allocator_service.secret_hash import hash_secret
    h = hash_secret("sek")
    resp = _decorated(monkeypatch, h, "Bearer nope")
    assert resp[1] == 401


def test_require_client_secret_rejects_missing_header(monkeypatch):
    resp = _decorated(monkeypatch, "$argon2id$h", None)
    assert resp[1] == 401


def test_require_client_secret_rejects_null_hash(monkeypatch):
    resp = _decorated(monkeypatch, None, "Bearer sek")
    assert resp[1] == 401


@pytest.fixture
def reg_client(app, monkeypatch):
    from lablink_allocator_service import main
    from lablink_allocator_service.secret_hash import hash_secret
    from lablink_allocator_service.providers.connectivity.allocator_proxied import (
        AllocatorProxiedClientConnectivity,
    )

    class _StubProvider:
        client_connectivity = AllocatorProxiedClientConnectivity()

    app.config["LABLINK_PROVIDER"] = _StubProvider()

    fake_db = MagicMock()
    fake_db.register_client.return_value = "vm-1"
    monkeypatch.setattr(main, "database", fake_db, raising=False)
    monkeypatch.setattr(main, "REGISTER_TOKEN", "tk_test_register", raising=False)
    fake_db.get_setting.return_value = hash_secret("tk_test_register")
    return app.test_client(), fake_db


def test_register_rejects_bad_token(reg_client):
    client, _ = reg_client
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": "vm-1", "machine_identity": "i-1"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401


def test_register_requires_hostname_and_identity(reg_client):
    client, _ = reg_client
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": "vm-1"},
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 400


def test_register_success_mints_secret(reg_client):
    client, fake_db = reg_client
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": "vm-1", "machine_identity": "i-1",
              "provider": "aws", "endpoint_url": "ws://x:6080",
              "provider_metadata": {"az": "a"}},
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["client_id"] == "vm-1"
    assert isinstance(body["client_secret"], str) and len(body["client_secret"]) >= 32
    assert body["connectivity"] == "allocator_proxied"
    assert body["register_token"] == "tk_test_register"
    assert "allocator_url" in body and "client_image" in body
    kw = fake_db.register_client.call_args.kwargs
    assert kw["client_secret_hash"].startswith("$argon2")
    assert kw["client_secret_hash"] != body["client_secret"]
    assert kw["machine_identity"] == "i-1"


def test_register_client_image_is_machine_image_only(reg_client):
    """cfg.machine.repository is the tutorial-repo-to-clone URL (see the
    AWS spec dict in main.py and TUTORIAL_REPO_TO_CLONE in client/start.sh)
    — an unrelated setting from cfg.machine.image (the actual docker image
    reference used verbatim on the AWS path as spec["image_name"]).
    client_image must never be built by prefixing repository onto image;
    the omega_config fixture sets both fields to prove they don't get
    concatenated for the manual/BYO registration path either."""
    client, _ = reg_client
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": "vm-1", "machine_identity": "i-1"},
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 200
    from lablink_allocator_service import main
    assert main.cfg.machine.repository, "fixture must set repository to exercise the bug"
    assert r.get_json()["client_image"] == main.cfg.machine.image


def test_status_requires_client_secret(reg_client):
    client, fake_db = reg_client
    fake_db.get_client_secret_hash.return_value = None
    r = client.get("/api/v1/clients/vm-1/status",
                    headers={"Authorization": "Bearer x"})
    assert r.status_code == 401


def test_status_returns_status(reg_client, monkeypatch):
    from lablink_allocator_service.secret_hash import hash_secret
    client, fake_db = reg_client
    fake_db.get_client_secret_hash.return_value = hash_secret("sek")
    fake_db.get_status_by_hostname.return_value = "running"
    r = client.get("/api/v1/clients/vm-1/status",
                    headers={"Authorization": "Bearer sek"})
    assert r.status_code == 200
    assert r.get_json() == {"client_id": "vm-1", "status": "running"}


def test_register_returns_409_on_none(reg_client):
    client, fake_db = reg_client
    fake_db.register_client.return_value = None
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": "vm-1", "machine_identity": "i-1"},
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 409


def test_register_returns_409_on_integrity_error(reg_client):
    import psycopg2
    client, fake_db = reg_client
    fake_db.register_client.side_effect = psycopg2.IntegrityError("dup")
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": "vm-1", "machine_identity": "i-1"},
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 409


def test_agent_token_global_exists():
    from lablink_allocator_service import main
    assert isinstance(main.AGENT_TOKEN, str) and len(main.AGENT_TOKEN) >= 32
    assert main.AGENT_TOKEN != main.REGISTER_TOKEN


def test_register_response_includes_agent_token(reg_client):
    client, fake_db = reg_client
    r = client.post("/api/v1/clients/register",
                     json={"hostname": "vm-1", "machine_identity": "i-1"},
                     headers={"Authorization": "Bearer tk_test_register"})
    assert r.status_code == 200
    from lablink_allocator_service import main
    assert r.get_json()["agent_token"] == main.AGENT_TOKEN


def test_register_response_includes_monitoring_block(reg_client, monkeypatch):
    """Register response must ship the monitoring block so start.sh can
    write it to /tmp/lablink-monitoring.json before launching the agent.
    The block is sourced verbatim from cfg.monitoring so operators can
    enable/disable Tier 1 without rebuilding client images."""
    from lablink_allocator_service import main

    monkeypatch.setattr(main.cfg.monitoring, "enabled", True, raising=False)
    monkeypatch.setattr(
        main.cfg.monitoring,
        "process_allowlist",
        ["sleap-train", "sleap-label"],
        raising=False,
    )

    client, _ = reg_client
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": "vm-1", "machine_identity": "i-1"},
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert "monitoring" in body
    m = body["monitoring"]
    assert m["enabled"] is True
    assert m["subject_window_patterns"] == []
    assert m["process_allowlist"] == ["sleap-train", "sleap-label"]
    assert m["watch_dir"] == "/home/client/Desktop"
    assert m["sample_interval_seconds"] == 2
    assert m["push_interval_seconds"] == 60


def test_register_response_monitoring_disabled_by_default(reg_client):
    """The default config has monitoring.enabled=false; the route must
    still ship a monitoring block with enabled=false so start.sh has an
    unambiguous gate (and never trips on a missing key)."""
    client, _ = reg_client
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": "vm-1", "machine_identity": "i-1"},
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["monitoring"]["enabled"] is False
    # process_allowlist still ships even when disabled — the client uses
    # it as soon as the operator re-enables monitoring without restarting.
    assert "sleap-train" in body["monitoring"]["process_allowlist"]


def test_register_response_omits_api_token(reg_client):
    """API_TOKEN is retired — registration response no longer includes it.
    Clients must use per-client client_secret for all authenticated endpoints."""
    client, fake_db = reg_client
    r = client.post("/api/v1/clients/register",
                     json={"hostname": "vm-1", "machine_identity": "i-1"},
                     headers={"Authorization": "Bearer tk_test_register"})
    assert r.status_code == 200
    body = r.get_json()
    assert "api_token" not in body
    assert body.get("client_secret") is not None
    assert body.get("agent_token") is not None


def test_register_response_omits_startup_script_when_disabled(reg_client):
    """startup_script.enabled=false (default) → empty payload + the
    config's on_error knob. BYO CLI uses the empty b64 as the signal
    to skip the mount, so the field must be present and empty rather
    than missing."""
    client, fake_db = reg_client
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": "vm-1", "machine_identity": "i-1"},
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["startup_script_b64"] == ""
    assert body["startup_on_error"] == "continue"


def test_register_response_includes_startup_script_when_enabled(
    reg_client, monkeypatch
):
    """startup_script.enabled=true + non-empty file at the conventional
    path → base64-encoded content is shipped in the response so the
    BYO CLI can write+mount it without filesystem access to the
    operator's host. Round-trip the bytes to catch encoder regressions."""
    import base64
    from unittest.mock import mock_open, patch

    from lablink_allocator_service import main
    monkeypatch.setattr(
        main.cfg.startup_script, "enabled", True, raising=False
    )
    monkeypatch.setattr(
        main.cfg.startup_script, "on_error", "fail", raising=False
    )

    fake_content = b"#!/bin/bash\necho hi from custom startup\n"
    client, fake_db = reg_client
    with patch(
        "lablink_allocator_service.routes.registration.open",
        mock_open(read_data=fake_content),
        create=True,
    ):
        r = client.post(
            "/api/v1/clients/register",
            json={"hostname": "vm-1", "machine_identity": "i-1"},
            headers={"Authorization": "Bearer tk_test_register"},
        )
    assert r.status_code == 200
    body = r.get_json()
    assert body["startup_script_b64"] == base64.b64encode(fake_content).decode()
    assert body["startup_on_error"] == "fail"
    # Round-trip back to bytes to guard against double-encoding regressions.
    assert base64.b64decode(body["startup_script_b64"]) == fake_content


def test_register_response_empty_when_enabled_but_file_missing(
    reg_client, monkeypatch
):
    """enabled=true but /config/custom-startup.sh absent (operator
    misconfiguration) → empty payload + warning logged. The CLI handles
    the empty payload by skipping the mount; the warning is the operator
    signal that something is wrong."""
    from lablink_allocator_service import main
    monkeypatch.setattr(
        main.cfg.startup_script, "enabled", True, raising=False
    )

    from unittest.mock import patch

    def _raise_fnf(*args, **kwargs):
        raise FileNotFoundError("/config/custom-startup.sh")

    client, fake_db = reg_client
    with patch(
        "lablink_allocator_service.routes.registration.open",
        _raise_fnf,
        create=True,
    ):
        r = client.post(
            "/api/v1/clients/register",
            json={"hostname": "vm-1", "machine_identity": "i-1"},
            headers={"Authorization": "Bearer tk_test_register"},
        )
    assert r.status_code == 200
    assert r.get_json()["startup_script_b64"] == ""


def test_register_response_empty_when_enabled_but_file_empty(
    reg_client, monkeypatch
):
    """enabled=true but the file is zero bytes — happens in the manual
    flow when the wizard's "Disabled" path is selected (deploy_compose
    still touches the file so the bind mount resolves). Must NOT ship
    `base64("")` (which would still trigger the CLI to materialize an
    empty script and mount it); ship `""` so the CLI skips the mount."""
    from unittest.mock import mock_open, patch

    from lablink_allocator_service import main
    monkeypatch.setattr(
        main.cfg.startup_script, "enabled", True, raising=False
    )

    client, fake_db = reg_client
    with patch(
        "lablink_allocator_service.routes.registration.open",
        mock_open(read_data=b""),
        create=True,
    ):
        r = client.post(
            "/api/v1/clients/register",
            json={"hostname": "vm-1", "machine_identity": "i-1"},
            headers={"Authorization": "Bearer tk_test_register"},
        )
    assert r.status_code == 200
    assert r.get_json()["startup_script_b64"] == ""


def test_register_response_honors_x_forwarded_proto(reg_client, monkeypatch):
    """nginx terminates TLS and proxies plain HTTP to Flask. With HTTPS
    enabled, the ProxyFix gate opens and request.host_url reflects the
    public scheme via X-Forwarded-Proto — so the registration response
    echoes back https://, which is what BYO clients write into
    client.env. Without that, BYO containers post over http://, nginx
    301s to https://, curl in start.sh drops the redirect, and
    vm-status never lands."""
    from lablink_allocator_service import main
    monkeypatch.setattr(main.cfg.ssl, "provider", "letsencrypt", raising=False)
    client, fake_db = reg_client
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": "vm-1", "machine_identity": "i-1"},
        headers={
            "Authorization": "Bearer tk_test_register",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "lablink.example.com",
        },
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["allocator_url"].startswith("https://"), body["allocator_url"]
    assert "lablink.example.com" in body["allocator_url"], body["allocator_url"]


def test_register_response_ignores_spoofed_proto_when_https_off(reg_client):
    """With ssl.provider='none' the allocator runs without nginx in
    front, so X-Forwarded-* headers come from an untrusted upstream —
    typically the client itself. ProxyFix must be off in that topology
    or a client could spoof X-Forwarded-Proto: https and have the
    registration response echo back an https URL the allocator can't
    actually serve. This test enforces the gate."""
    client, fake_db = reg_client
    # The default omega_config has ssl.provider='none' — no monkeypatch
    # needed; just confirm the spoof is ignored.
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": "vm-1", "machine_identity": "i-1"},
        headers={
            "Authorization": "Bearer tk_test_register",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "evil.example.com",
        },
    )
    assert r.status_code == 200
    body = r.get_json()
    assert not body["allocator_url"].startswith("https://"), body["allocator_url"]
    assert "evil.example.com" not in body["allocator_url"], body["allocator_url"]


def test_unregister_rejects_missing_header(reg_client):
    """No Authorization header → 401."""
    client, _ = reg_client
    r = client.delete("/api/v1/clients/vm-1")
    assert r.status_code == 401


def test_unregister_rejects_bad_token(reg_client):
    """Bearer token that does not verify against client_secret_hash → 401."""
    from lablink_allocator_service.secret_hash import hash_secret

    client, fake_db = reg_client
    fake_db.get_client_secret_hash.return_value = hash_secret("real-secret")
    r = client.delete(
        "/api/v1/clients/vm-1",
        headers={"Authorization": "Bearer wrong-secret"},
    )
    assert r.status_code == 401


def test_unregister_rejects_unknown_client_id(reg_client):
    """No secret hash on file (unknown client_id) → 401, not 404 —
    don't let callers enumerate registered client_ids."""
    client, fake_db = reg_client
    fake_db.get_client_secret_hash.return_value = None
    r = client.delete(
        "/api/v1/clients/vm-1",
        headers={"Authorization": "Bearer anything"},
    )
    assert r.status_code == 401


def test_unregister_returns_404_when_no_row(reg_client):
    """Auth passes but the row is gone (already deleted / race) → 404."""
    from lablink_allocator_service.secret_hash import hash_secret

    client, fake_db = reg_client
    fake_db.get_client_secret_hash.return_value = hash_secret("sek")
    fake_db.unregister_client.return_value = False
    r = client.delete(
        "/api/v1/clients/vm-1",
        headers={"Authorization": "Bearer sek"},
    )
    assert r.status_code == 404


def test_unregister_success(reg_client):
    """Valid bearer + row exists → 200, JSON body, db.unregister_client called."""
    from lablink_allocator_service.secret_hash import hash_secret

    client, fake_db = reg_client
    fake_db.get_client_secret_hash.return_value = hash_secret("sek")
    fake_db.unregister_client.return_value = True
    r = client.delete(
        "/api/v1/clients/vm-1",
        headers={"Authorization": "Bearer sek"},
    )
    assert r.status_code == 200
    assert r.get_json() == {"client_id": "vm-1", "status": "unregistered"}
    fake_db.unregister_client.assert_called_once_with("vm-1")


# ---- GET /api/v1/clients (list endpoint) ---------------------------------

def test_list_clients_rejects_missing_auth(reg_client):
    client, _ = reg_client
    r = client.get("/api/v1/clients")
    assert r.status_code == 401


def test_list_clients_rejects_bad_bearer(reg_client):
    client, _ = reg_client
    r = client.get(
        "/api/v1/clients",
        headers={"Authorization": "Bearer wrong-api-token"},
    )
    assert r.status_code == 401


def test_list_clients_accepts_admin_basic(reg_client, admin_headers):
    client, fake_db = reg_client
    fake_db.list_registered_clients.return_value = []
    r = client.get("/api/v1/clients", headers=admin_headers)
    assert r.status_code == 200
    assert r.get_json() == {"clients": []}


def test_register_rejects_lan_ip_metadata_against_mesh_overlay_allocator(
    reg_client, monkeypatch,
):
    """A manual client that auto-detected --lan-ip (forgot
    --overlay-hostname) must not silently register against a
    mesh_overlay-configured allocator: the browser would end up trying
    to dial the client's private LAN IP directly, which is unreachable
    off that LAN -- exactly the failure mode this guards against."""
    from lablink_allocator_service.providers.connectivity.mesh_overlay import (
        MeshOverlayClientConnectivity,
    )

    client, fake_db = reg_client
    client.application.config["LABLINK_PROVIDER"].client_connectivity = (
        MeshOverlayClientConnectivity()
    )
    r = client.post(
        "/api/v1/clients/register",
        json={
            "hostname": "vm-1", "machine_identity": "i-1",
            "provider": "manual", "provider_metadata": {"lan_ip": "1.2.3.4"},
        },
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 400
    assert "overlay-hostname" in r.get_json()["error"]
    fake_db.register_client.assert_not_called()


def test_register_rejects_overlay_hostname_metadata_against_lan_direct_allocator(
    reg_client,
):
    """The inverse mismatch: --overlay-hostname against a lan_direct
    (real-BYO) allocator must also be rejected rather than silently
    accepted -- this connectivity mode has no Tailscale sidecar to
    resolve the hostname through."""
    client, fake_db = reg_client
    # reg_client's default stub is AllocatorProxiedClientConnectivity
    # (name != "mesh_overlay"), matching a non-mesh_overlay deployment.
    r = client.post(
        "/api/v1/clients/register",
        json={
            "hostname": "vm-1", "machine_identity": "i-1",
            "provider": "manual",
            "provider_metadata": {"overlay_hostname": "classroom-1"},
        },
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 400
    assert "overlay-hostname" in r.get_json()["error"]
    fake_db.register_client.assert_not_called()


def test_register_accepts_overlay_hostname_metadata_against_mesh_overlay_allocator(
    reg_client,
):
    """The matching, correct case: --overlay-hostname against a
    mesh_overlay-configured allocator registers normally."""
    from lablink_allocator_service.providers.connectivity.mesh_overlay import (
        MeshOverlayClientConnectivity,
    )

    client, fake_db = reg_client
    client.application.config["LABLINK_PROVIDER"].client_connectivity = (
        MeshOverlayClientConnectivity()
    )
    r = client.post(
        "/api/v1/clients/register",
        json={
            "hostname": "vm-1", "machine_identity": "i-1",
            "provider": "manual",
            "provider_metadata": {"overlay_hostname": "classroom-1"},
        },
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 200
    fake_db.register_client.assert_called_once()


def test_register_accepts_lan_ip_metadata_against_lan_direct_allocator(reg_client):
    """Regression guard: the ordinary real-BYO case (--lan-ip against a
    non-mesh_overlay allocator) is unaffected by the new check."""
    client, fake_db = reg_client
    r = client.post(
        "/api/v1/clients/register",
        json={
            "hostname": "vm-1", "machine_identity": "i-1",
            "provider": "manual", "provider_metadata": {"lan_ip": "1.2.3.4"},
        },
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 200
    fake_db.register_client.assert_called_once()


def test_register_skips_connectivity_check_for_non_manual_provider(reg_client):
    """AWS-provisioned VMs never send lan_ip/overlay_hostname metadata
    and don't go through this CLI-driven flow -- the check must not
    fire for provider != 'manual' regardless of metadata shape."""
    client, fake_db = reg_client
    r = client.post(
        "/api/v1/clients/register",
        json={
            "hostname": "vm-1", "machine_identity": "i-1",
            "provider": "aws",
            "provider_metadata": {"overlay_hostname": "classroom-1"},
        },
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 200
    fake_db.register_client.assert_called_once()


def test_register_fallback_provider_construction_includes_connectivity(
    reg_client, monkeypatch,
):
    """When LABLINK_PROVIDER isn't already cached in app.config, the
    fallback ``main.get_provider(...)`` call in this view must still pass
    ``connectivity=main.cfg.manual.connectivity`` through -- otherwise it
    silently defaults to lan_direct regardless of the deployment's actual
    configured connectivity, which would make the mismatched-metadata
    check above reject legitimate --overlay-hostname registrations against
    a mesh_overlay allocator. Mirrors the connectivity= fix already applied
    to the admin_connect_vm/submit_vm_details fallback call sites in
    main.py."""
    from lablink_allocator_service import main

    client, fake_db = reg_client
    monkeypatch.delitem(client.application.config, "LABLINK_PROVIDER")
    monkeypatch.setattr(main.cfg, "provider", "manual", raising=False)
    monkeypatch.setattr(
        main.cfg.manual, "connectivity", "mesh_overlay", raising=False
    )

    r = client.post(
        "/api/v1/clients/register",
        json={
            "hostname": "vm-1", "machine_identity": "i-1",
            "provider": "manual",
            "provider_metadata": {"overlay_hostname": "classroom-1"},
        },
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 200
    fake_db.register_client.assert_called_once()


def test_list_clients_returns_safe_fields(reg_client, admin_headers):
    from datetime import datetime

    client, fake_db = reg_client
    fake_db.list_registered_clients.return_value = [
        {
            "hostname": "byo-1",
            "provider": "manual",
            "endpoint_url": "ws://byo-1.local:6080",
            "inuse": False,
            "status": "running",
            "healthy": "true",
            "gpu_present": True,
            "gpu_model": "RTX 4090",
            "last_seen_at": datetime(2026, 5, 27, 12, 0, 0),
        },
        {
            "hostname": "vm-2",
            "provider": "aws",
            "endpoint_url": None,
            "inuse": True,
            "status": "running",
            "healthy": None,
            "gpu_present": None,
            "gpu_model": None,
            "last_seen_at": None,
        },
    ]
    r = client.get("/api/v1/clients", headers=admin_headers)
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["clients"]) == 2
    byo, vm = body["clients"]
    assert byo["hostname"] == "byo-1"
    assert byo["provider"] == "manual"
    assert byo["gpu_present"] is True
    assert byo["gpu_model"] == "RTX 4090"
    assert byo["last_seen_at"] == "2026-05-27T12:00:00"
    assert vm["hostname"] == "vm-2"
    assert vm["inuse"] is True
    # No secret fields leaked into the response.
    for c in body["clients"]:
        assert "client_secret_hash" not in c
        assert "machine_identity" not in c
        assert "cloudinitlogs" not in c
        assert "dockerlogs" not in c
