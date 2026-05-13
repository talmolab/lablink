"""Tests for the GET /desktop route."""
import uuid

import pytest

from lablink_allocator_service.signed_cookie import sign


SEED_SECRET = "test-secret"


def _ensure_session_columns(real_db):
    """The real_db fixture creates a minimal vms table; extend it
    with the columns Task 12's /desktop handler reads."""
    with real_db._cursor as cur:
        cur.execute(
            "ALTER TABLE vms "
            "ADD COLUMN IF NOT EXISTS status TEXT, "
            "ADD COLUMN IF NOT EXISTS useremail TEXT, "
            "ADD COLUMN IF NOT EXISTS sessionid UUID, "
            "ADD COLUMN IF NOT EXISTS browsertoken TEXT"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS settings ("
            "  key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        # Force-set the secret so the route signs and verifies with
        # SEED_SECRET regardless of what prior tests left in the row.
        cur.execute(
            "INSERT INTO settings (key, value) "
            "VALUES ('cookie_signing_secret', %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (SEED_SECRET,),
        )


@pytest.fixture
def client_with_db(real_db, monkeypatch):
    """A Flask test client where `database` is the real_db PostgresqlDatabase
    and `app.config['DB_POOL']` points at its pool, so the desktop route can
    read the signing secret."""
    _ensure_session_columns(real_db)

    # Import main lazily (mirrors the existing `app` fixture pattern) so we
    # can substitute the database global before any route runs.
    import lablink_allocator_service.main as main_module

    monkeypatch.setattr(main_module, "database", real_db, raising=True)
    main_module.app.config["DB_POOL"] = real_db._pool
    main_module.app.config["VM_TABLE_NAME"] = real_db.table_name
    return main_module.app.test_client()


def test_desktop_redirects_without_cookie(client_with_db):
    resp = client_with_db.get("/desktop", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_desktop_renders_with_valid_cookie(client_with_db, real_db):
    sid = str(uuid.uuid4())
    with real_db._cursor as cur:
        cur.execute("DELETE FROM vms WHERE hostname = 'host-task12'")
        cur.execute(
            "INSERT INTO vms (hostname, status, useremail, "
            "                 sessionid, browsertoken) "
            "VALUES ('host-task12', 'running', 'sam@x.com', "
            "        %s, 'tok-abc')",
            (sid,),
        )
    client_with_db.set_cookie("lablink_session", sign(sid, secret=SEED_SECRET))

    resp = client_with_db.get("/desktop")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "/proxy/tok-abc" in body
    # The KasmVNC password should NOT be in the HTML on the AWS path —
    # nginx attaches it server-side via auth_request. The browser token
    # is fine to embed; the password is not.
    assert "VncPassword" not in body  # safety: the column literal name
    # ws:// or wss:// scheme in the page
    assert ("/proxy/tok-abc" in body) and (
        ("ws://" in body) or ("wss://" in body)
    )


def test_desktop_redirects_when_status_not_running(client_with_db, real_db):
    sid = str(uuid.uuid4())
    with real_db._cursor as cur:
        cur.execute("DELETE FROM vms WHERE hostname = 'host-task12-failed'")
        cur.execute(
            "INSERT INTO vms (hostname, status, useremail, "
            "                 sessionid, browsertoken) "
            "VALUES ('host-task12-failed', 'failed', 'sam@x.com', "
            "        %s, 'tok-xyz')",
            (sid,),
        )
    client_with_db.set_cookie("lablink_session", sign(sid, secret=SEED_SECRET))
    resp = client_with_db.get("/desktop", follow_redirects=False)
    assert resp.status_code == 302
