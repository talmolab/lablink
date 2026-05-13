"""Tests for POST /internal/proxy_auth — the nginx auth_request callback."""
import uuid

import pytest

from lablink_allocator_service.signed_cookie import sign


SEED_SECRET = "test-secret"


def _ensure_session_columns(real_db):
    """Extend the minimal vms test table with the columns the
    /internal/proxy_auth handler reads, and seed the cookie secret."""
    with real_db._cursor as cur:
        cur.execute(
            "ALTER TABLE vms "
            "ADD COLUMN IF NOT EXISTS status TEXT, "
            "ADD COLUMN IF NOT EXISTS useremail TEXT, "
            "ADD COLUMN IF NOT EXISTS sessionid UUID, "
            "ADD COLUMN IF NOT EXISTS browsertoken TEXT, "
            "ADD COLUMN IF NOT EXISTS vncpassword TEXT, "
            "ADD COLUMN IF NOT EXISTS upstream TEXT"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS settings ("
            "  key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        # Force-set the secret so this fixture doesn't depend on what
        # other tests left behind.
        cur.execute(
            "INSERT INTO settings (key, value) "
            "VALUES ('cookie_signing_secret', %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (SEED_SECRET,),
        )


@pytest.fixture
def client_with_db(real_db, monkeypatch):
    """Flask test client wired to the real_db PostgresqlDatabase."""
    _ensure_session_columns(real_db)
    import lablink_allocator_service.main as main_module
    monkeypatch.setattr(main_module, "database", real_db, raising=True)
    main_module.app.config["DB_POOL"] = real_db._pool
    main_module.app.config["VM_TABLE_NAME"] = real_db.table_name
    return main_module.app.test_client()


def _seed_running_row(real_db, *, hostname, token="tok",
                      email="sam@x.com"):
    sid = str(uuid.uuid4())
    with real_db._cursor as cur:
        cur.execute("DELETE FROM vms WHERE hostname = %s", (hostname,))
        cur.execute(
            "INSERT INTO vms (hostname, status, useremail, "
            "                 sessionid, browsertoken, vncpassword, upstream) "
            "VALUES (%s, 'running', %s, %s, %s, 'pw', '10.0.0.5:6080')",
            (hostname, email, sid, token),
        )
    return sid


def test_proxy_auth_happy_path(client_with_db, real_db):
    sid = _seed_running_row(real_db, hostname="host-pa-1", token="tok")
    client_with_db.set_cookie("lablink_session", sign(sid, secret=SEED_SECRET))
    resp = client_with_db.post(
        "/internal/proxy_auth",
        headers={"X-Original-URI": "/proxy/tok"},
    )
    assert resp.status_code == 200
    assert resp.headers["X-Upstream"] == "10.0.0.5:6080"
    # KasmVNC expects HTTP Basic Auth with a username; nginx forwards
    # this header as `Authorization:` on the upstream WebSocket upgrade.
    import base64
    expected = "Basic " + base64.b64encode(b"kasm_user:pw").decode()
    assert resp.headers["X-Auth-Basic"] == expected
    assert "X-VNC-Password" not in resp.headers


def test_proxy_auth_rejects_bad_cookie(client_with_db, real_db):
    _seed_running_row(real_db, hostname="host-pa-2")
    client_with_db.set_cookie("lablink_session", "garbage")
    resp = client_with_db.post(
        "/internal/proxy_auth",
        headers={"X-Original-URI": "/proxy/tok"},
    )
    assert resp.status_code == 401


def test_proxy_auth_rejects_token_mismatch(client_with_db, real_db):
    sid = _seed_running_row(real_db, hostname="host-pa-3", token="real")
    client_with_db.set_cookie("lablink_session", sign(sid, secret=SEED_SECRET))
    resp = client_with_db.post(
        "/internal/proxy_auth",
        headers={"X-Original-URI": "/proxy/wrong"},
    )
    assert resp.status_code == 401


def test_proxy_auth_rejects_failed_status(client_with_db, real_db):
    sid = str(uuid.uuid4())
    with real_db._cursor as cur:
        cur.execute("DELETE FROM vms WHERE hostname = 'host-pa-4'")
        cur.execute(
            "INSERT INTO vms (hostname, status, useremail, "
            "                 sessionid, browsertoken, vncpassword, upstream) "
            "VALUES ('host-pa-4', 'failed', 'sam@x.com', "
            "        %s, 'tok', 'pw', '10.0.0.5:6080')",
            (sid,),
        )
    client_with_db.set_cookie("lablink_session", sign(sid, secret=SEED_SECRET))
    resp = client_with_db.post(
        "/internal/proxy_auth",
        headers={"X-Original-URI": "/proxy/tok"},
    )
    assert resp.status_code == 401
