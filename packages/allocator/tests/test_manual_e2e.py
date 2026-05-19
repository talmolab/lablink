"""D1 hermetic stubbed-agent end-to-end (spec Testing -> Layer 1).

Manual / LAN-direct path, allocator-side only: no real network, no GPU,
no Postgres.  Drives the three D1 phases against ONE logical hostname so
the data contract is shown to flow end-to-end:

  1. POST /api/v1/clients/register  -> response carries agent_token and
     connectivity == "lan_direct" (manual provider selected).
  2. LANDirectClientConnectivity.prepare_browser_session -> persists
     browser_ws_url="ws://<lan_ip>:6080" + browser_credential=<pw> via
     the cursor (agent rotate stubbed; no socket).
  3. GET /desktop -> 200 in-page render embedding the lan_ip/port and the
     credential, with NO "?path=proxy/" redirect.

The three phases legitimately use different stubs (Flask client + mock
db / mock cursor / row-stub) -- we assert the contract, not a shared DB.
Fixture / patch conventions mirror the sibling modules:
  - test_registration_api.py  (reg_client: LABLINK_PROVIDER + db stub)
  - test_lan_direct.py        (_post_rotate monkeypatch + mock cursor)
  - test_desktop_route.py     (desktop_client_with_row mock pool/cursor)
"""
import uuid

from unittest.mock import MagicMock

import pytest

from lablink_allocator_service.providers.manual import ManualProvider
from lablink_allocator_service.signed_cookie import sign


SEED_SECRET = "test-secret"
HOSTNAME = "vm-e2e"
LAN_IP = "10.0.0.5"
EXPECTED_WS_URL = f"ws://{LAN_IP}:6080"


@pytest.fixture
def manual_reg_client(app, monkeypatch):
    """Flask test client wired to the manual provider.

    Mirrors test_registration_api.py::reg_client but swaps the stub
    provider's connectivity for LANDirectClientConnectivity so the
    register view selects the manual / lan_direct path.
    """
    from lablink_allocator_service import main
    from lablink_allocator_service.secret_hash import hash_secret

    app.config["LABLINK_PROVIDER"] = ManualProvider()

    fake_db = MagicMock()
    fake_db.register_client.return_value = HOSTNAME
    monkeypatch.setattr(main, "database", fake_db, raising=False)
    monkeypatch.setattr(main, "REGISTER_TOKEN", "tk_test_register", raising=False)
    fake_db.get_setting.return_value = hash_secret("tk_test_register")
    return app.test_client(), fake_db


def test_manual_lan_direct_e2e(manual_reg_client, monkeypatch):
    # -------------------------------------------------------------------
    # Phase 1 -- register: manual provider -> agent_token + lan_direct.
    # -------------------------------------------------------------------
    client, _ = manual_reg_client
    r = client.post(
        "/api/v1/clients/register",
        json={"hostname": HOSTNAME, "machine_identity": "i-e2e"},
        headers={"Authorization": "Bearer tk_test_register"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["agent_token"]  # present + non-empty
    assert body["connectivity"] == "lan_direct"

    from lablink_allocator_service import main

    agent_token = body["agent_token"]
    assert agent_token == main.AGENT_TOKEN

    # -------------------------------------------------------------------
    # Phase 2 -- prepare_browser_session: stub agent rotate (no network),
    # capture the UPDATE the cursor receives.
    # -------------------------------------------------------------------
    import lablink_allocator_service.client_session as cs
    from lablink_allocator_service.providers.connectivity.lan_direct import (
        LANDirectClientConnectivity,
    )

    posted = {}
    monkeypatch.setattr(
        cs,
        "_post_rotate",
        lambda url, body_, *, bearer: posted.update(
            url=url, body=body_, bearer=bearer
        ),
        raising=True,
    )

    executed = {}

    class _Cur:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params):
            executed["sql"] = sql
            executed["params"] = params

    class _DB:
        table_name = "vms"
        _cursor = _Cur()

        def get_lan_ip(self, hostname):
            assert hostname == HOSTNAME
            return LAN_IP

    session_id = uuid.uuid4()
    target = LANDirectClientConnectivity().prepare_browser_session(
        database=_DB(),
        hostname=HOSTNAME,
        session_id=session_id,
        browser_token="btok-e2e",
        agent_token=agent_token,
    )

    # Agent rotate was stubbed -> no socket; bearer is the agent_token
    # the register response handed back.
    assert posted["url"] == f"http://{LAN_IP}:7070/api/session/start"
    assert posted["bearer"] == agent_token

    # Returned target carries the direct ws:// URL + a non-empty
    # generated credential (secrets.token_urlsafe(24); value not asserted).
    assert target.ws_url == EXPECTED_WS_URL
    assert target.browser_credential
    password = target.browser_credential

    # Same credential flows onto the wire and into the persisted UPDATE.
    assert posted["body"] == {"password": password}
    params = executed["params"]
    assert "browser_ws_url" in executed["sql"]
    assert "browser_credential" in executed["sql"]
    assert EXPECTED_WS_URL in params
    assert password in params

    # -------------------------------------------------------------------
    # Phase 3 -- /desktop: row stub returns the two persisted columns ->
    # 200 in-page render with lan_ip/port + credential, NO proxy redirect.
    # (Mirrors test_desktop_route.py::desktop_client_with_row.)
    # -------------------------------------------------------------------
    import lablink_allocator_service.main as main_module

    sid = str(uuid.uuid4())
    signed = sign(sid, secret=SEED_SECRET)

    mock_cur = MagicMock()
    mock_cur.__enter__ = lambda s: s
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchone.return_value = (EXPECTED_WS_URL, password)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cur

    mock_pool = MagicMock()
    mock_pool.getconn.return_value = mock_conn

    main_module.app.config["DB_POOL"] = mock_pool
    main_module.app.config["VM_TABLE_NAME"] = "vms"

    monkeypatch.setattr(
        "lablink_allocator_service.routes.desktop.get_or_create_cookie_secret",
        lambda _: SEED_SECRET,
        raising=True,
    )

    desktop_client = main_module.app.test_client()
    desktop_client.set_cookie("lablink_session", signed)
    resp = desktop_client.get("/desktop")

    assert resp.status_code == 200  # rendered page, not a redirect
    page = resp.get_data(as_text=True)
    assert LAN_IP in page and "6080" in page
    assert password in page  # credential in-page (localStorage), not in URL
    assert "?path=proxy/" not in page
