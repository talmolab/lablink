"""Tests for the GET /desktop route."""
import uuid
from unittest.mock import MagicMock

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
            "ADD COLUMN IF NOT EXISTS browsertoken TEXT, "
            "ADD COLUMN IF NOT EXISTS browser_ws_url TEXT, "
            "ADD COLUMN IF NOT EXISTS browser_credential TEXT"
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


def test_desktop_redirects_to_kasmvnc_viewer_with_valid_cookie(
    client_with_db, real_db
):
    sid = str(uuid.uuid4())
    with real_db._cursor as cur:
        cur.execute("DELETE FROM vms WHERE hostname = 'host-task12'")
        cur.execute(
            "INSERT INTO vms (hostname, status, useremail, "
            "                 sessionid, browsertoken, "
            "                 browser_ws_url, browser_credential) "
            "VALUES ('host-task12', 'running', 'sam@x.com', "
            "        %s, 'tok-abc', 'proxy/tok-abc', NULL)",
            (sid,),
        )
    client_with_db.set_cookie("lablink_session", sign(sid, secret=SEED_SECRET))

    # /desktop now redirects into KasmVNC's bundled noVNC viewer (served
    # at /static/novnc/vnc.html from /usr/share/kasmvnc/www/). Debian's
    # generic novnc package would 404 in production now — we removed
    # the custom desktop.html template and the apt install in favor of
    # the Kasm-bundled viewer, which is the only one protocol-compatible
    # with kasmvncserver.
    resp = client_with_db.get("/desktop", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["Location"]
    assert "/static/novnc/vnc.html" in location
    assert "path=proxy/tok-abc" in location
    assert "autoconnect=1" in location


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


# ---------------------------------------------------------------------------
# Mock-based fixture: controls (browser_ws_url, browser_credential) directly
# without requiring a real Postgres connection.
# ---------------------------------------------------------------------------

@pytest.fixture
def desktop_client_with_row(monkeypatch):
    """Factory fixture: yields a callable that returns a Flask test client
    whose /desktop row lookup returns ``(ws_url, cred, hostname)`` for a valid running
    session + signed cookie.  No real Postgres required."""

    def _make(*, ws_url, cred, suffix="", hostname="host-x"):
        import lablink_allocator_service.main as main_module

        # Stable session id — sign it (optionally with a suffix) with SEED_SECRET.
        sid = str(uuid.uuid4())
        payload = f"{sid}:{suffix}" if suffix else sid
        signed = sign(payload, secret=SEED_SECRET)

        # Mock cursor: fetchone returns the three new columns.
        mock_cur = MagicMock()
        mock_cur.__enter__ = lambda s: s
        mock_cur.__exit__ = MagicMock(return_value=False)
        mock_cur.fetchone.return_value = (ws_url, cred, hostname)

        # Mock connection: cursor() returns mock_cur.
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        # Mock pool: getconn returns the mock connection, putconn is a no-op.
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = mock_conn

        main_module.app.config["DB_POOL"] = mock_pool
        main_module.app.config["VM_TABLE_NAME"] = "vms"

        # Stub get_or_create_cookie_secret so the route verifies with SEED_SECRET.
        monkeypatch.setattr(
            "lablink_allocator_service.routes.desktop.get_or_create_cookie_secret",
            lambda _: SEED_SECRET,
            raising=True,
        )

        flask_client = main_module.app.test_client()
        flask_client.set_cookie("lablink_session", signed)
        return flask_client

    return _make


def test_desktop_aws_byte_identical(desktop_client_with_row):
    client = desktop_client_with_row(ws_url="proxy/btok123", cred=None)
    r = client.get("/desktop")
    assert r.status_code == 302
    assert r.headers["Location"] == (
        "/static/novnc/vnc.html?path=proxy/btok123&autoconnect=1&resize=remote"
    )


def test_desktop_lan_direct_renders_direct_with_credential(desktop_client_with_row):
    client = desktop_client_with_row(ws_url="ws://10.0.0.9:6080", cred="seshpw")
    r = client.get("/desktop")
    assert r.status_code == 200          # rendered page, not a redirect
    body = r.get_data(as_text=True)
    assert "10.0.0.9" in body and "6080" in body
    # The credential MUST land in vnc.html's ?password=, which the bundled
    # KasmVNC noVNC consumes through the RFB VncAuth handshake — that is
    # the only browser-side route to authenticate without an HTTP proxy
    # injecting BasicAuth (which browsers won't do for WS upgrades).
    assert "&password=seshpw" in body
    assert "?path=proxy/" not in body
    # location.replace keeps the password URL out of session history;
    # access_log off in lablink-nginx.conf keeps it out of server logs.
    assert "location.replace" in body


def test_desktop_lan_direct_urlencodes_credential(desktop_client_with_row):
    """A credential containing URL-unsafe bytes must be percent-encoded
    in the query string — otherwise noVNC parses garbage and the VNC
    auth handshake fails with a non-obvious error."""
    client = desktop_client_with_row(ws_url="ws://10.0.0.9:6080", cred="a/b+c=d")
    body = client.get("/desktop").get_data(as_text=True)
    # `/`, `+`, `=` all need percent-encoding inside a value position.
    assert "&password=a%2Fb%2Bc%3Dd" in body
    assert "a/b+c=d" not in body


def test_desktop_view_only_appends_query_param(desktop_client_with_row):
    client = desktop_client_with_row(
        ws_url="proxy/btok123", cred=None, suffix="view_only"
    )
    r = client.get("/desktop")
    assert r.status_code == 302
    assert r.headers["Location"] == (
        "/static/novnc/vnc.html?path=proxy/btok123"
        "&autoconnect=1&resize=remote&view_only=1"
    )


def test_desktop_plain_session_has_no_view_only_param(desktop_client_with_row):
    client = desktop_client_with_row(ws_url="proxy/btok123", cred=None)
    r = client.get("/desktop")
    assert "view_only" not in r.headers["Location"]


def test_desktop_admin_session_renders_wrapper_with_release_form(
    desktop_client_with_row,
):
    client = desktop_client_with_row(
        ws_url="proxy/tok-admin", cred=None,
        suffix="admin_session", hostname="host-troubleshoot",
    )
    r = client.get("/desktop")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Admin session on host-troubleshoot" in body
    assert (
        '<form method="POST" action="/admin/instances/host-troubleshoot/release">'
        in body
    )
    assert (
        'src="/static/novnc/vnc.html?path=proxy/tok-admin'
        '&autoconnect=1&resize=remote"' in body
    )


def test_desktop_admin_session_escapes_hostname(desktop_client_with_row):
    client = desktop_client_with_row(
        ws_url="proxy/tok-x", cred=None,
        suffix="admin_session", hostname="host<script>",
    )
    body = client.get("/desktop").get_data(as_text=True)
    assert "<script>" not in body
    assert "&lt;script&gt;" in body
