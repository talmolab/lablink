import uuid
from unittest.mock import MagicMock, patch

import pytest
import requests


# Per-test AGENT_TOKEN that matches what main.AGENT_TOKEN would generate
# in production; passed explicitly to prepare_browser_session.
AGENT_TOKEN = "test-agent-token"


@pytest.fixture
def vms_full_schema(real_db):
    """real_db with every per-session column the production schema has.

    Tests in this file used to each duplicate the same ALTER TABLE block;
    one fixture means the next column addition is a one-line edit instead
    of N. ADD COLUMN IF NOT EXISTS makes the union safe across tests that
    only consult a subset of the columns.
    """
    with real_db._cursor as cur:
        cur.execute(
            "ALTER TABLE vms "
            "ADD COLUMN IF NOT EXISTS status TEXT, "
            "ADD COLUMN IF NOT EXISTS useremail TEXT, "
            "ADD COLUMN IF NOT EXISTS sessionid UUID, "
            "ADD COLUMN IF NOT EXISTS browsertoken TEXT, "
            "ADD COLUMN IF NOT EXISTS vncpassword TEXT, "
            "ADD COLUMN IF NOT EXISTS upstream TEXT, "
            "ADD COLUMN IF NOT EXISTS browser_ws_url TEXT, "
            "ADD COLUMN IF NOT EXISTS browser_credential TEXT, "
            "ADD COLUMN IF NOT EXISTS sessionstartedat TIMESTAMPTZ, "
            "ADD COLUMN IF NOT EXISTS provider TEXT, "
            "ADD COLUMN IF NOT EXISTS endpoint_url TEXT, "
            "ADD COLUMN IF NOT EXISTS provider_metadata JSONB"
        )
    return real_db


def test_happy_path_rotates_and_persists(vms_full_schema):
    """prepare_browser_session: rotates VNC password on the agent and
    updates the per-session columns on the clients row."""
    with vms_full_schema._cursor as cur:
        cur.execute("DELETE FROM vms WHERE hostname = 'host-task10'")
        cur.execute(
            "INSERT INTO vms (hostname, status, useremail) "
            "VALUES ('host-task10', 'running', 'sam@x.com')"
        )

    session_id = uuid.uuid4()

    from lablink_allocator_service.client_session import (
        prepare_browser_session,
    )

    with patch(
        "lablink_allocator_service.client_session.requests.post"
    ) as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200, raise_for_status=lambda: None
        )
        target = prepare_browser_session(
            database=vms_full_schema,
            hostname="host-task10",
            session_id=session_id,
            browser_token="tok-abc",
            agent_token=AGENT_TOKEN,
            fallback_fn=lambda h: "10.0.0.5",
        )

    # Agent POST: correct URL, Bearer header sourced from agent_token kwarg,
    # body carries only the rotated password (the agent doesn't need
    # session_id or browser_token — those are allocator-side bookkeeping).
    mock_post.assert_called_once()
    url = mock_post.call_args[0][0]
    kwargs = mock_post.call_args[1]
    assert url == "http://10.0.0.5:7070/api/session/start"
    assert kwargs["headers"]["Authorization"] == f"Bearer {AGENT_TOKEN}"
    assert "password" in kwargs["json"]
    assert kwargs["json"].keys() == {"password"}

    # Row updated with per-session columns. The password matches what we
    # sent on the wire, so /internal/proxy_auth's later lookup will yield
    # the same value the client agent installed.
    with vms_full_schema._cursor as cur:
        cur.execute(
            "SELECT sessionid, browsertoken, vncpassword, upstream "
            "FROM vms WHERE hostname = 'host-task10'"
        )
        row = cur.fetchone()
    assert str(row[0]) == str(session_id)
    assert row[1] == "tok-abc"
    assert row[2] == kwargs["json"]["password"]
    assert row[3] == "10.0.0.5:6080"
    assert target.ws_url == "proxy/tok-abc"
    assert target.browser_credential is None


def test_one_retry_then_raises(vms_full_schema):
    with vms_full_schema._cursor as cur:
        cur.execute("DELETE FROM vms WHERE hostname = 'host-task10-fail'")
        cur.execute(
            "INSERT INTO vms (hostname, status, useremail) "
            "VALUES ('host-task10-fail', 'running', 'sam@x.com')"
        )

    from lablink_allocator_service.client_session import (
        RotationFailed,
        prepare_browser_session,
    )

    with patch(
        "lablink_allocator_service.client_session.requests.post",
        side_effect=requests.RequestException("boom"),
    ) as mock_post:
        with pytest.raises(RotationFailed):
            prepare_browser_session(
                database=vms_full_schema,
                hostname="host-task10-fail",
                session_id=uuid.uuid4(),
                browser_token="t",
                agent_token=AGENT_TOKEN,
                fallback_fn=lambda h: "10.0.0.5",
            )

    assert mock_post.call_count == 2  # initial + one retry


def test_prepare_browser_session_persists_render_columns(monkeypatch):
    import lablink_allocator_service.client_session as cs
    import uuid

    monkeypatch.setattr(cs, "_lookup_private_ip", lambda h, db, *, fallback_fn=None: "10.0.0.5")
    posted = {}
    monkeypatch.setattr(cs, "_post_rotate",
                        lambda url, body, *, bearer: posted.update(
                            url=url, body=body, bearer=bearer))

    executed = {}
    class _Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, sql, params):
            executed["sql"] = sql
            executed["params"] = params
    class _DB:
        table_name = "vms"
        _cursor = _Cur()

    t = cs.prepare_browser_session(
        database=_DB(), hostname="vm-1", session_id=uuid.uuid4(),
        browser_token="btok", agent_token="agenttok",
    )
    assert posted["bearer"] == "agenttok"
    assert posted["body"] == {"password": executed["params"][2]}  # vncpassword param
    assert t.ws_url == "proxy/btok"
    assert t.browser_credential is None
    assert "browser_ws_url" in executed["sql"]
    assert "browser_credential = NULL" in executed["sql"]


def test_byo_row_uses_stored_lan_ip_without_ec2_lookup(vms_full_schema):
    """BYO rows record provider_metadata.lan_ip at registration time.
    Rotation must use it instead of looking up by EC2 Name tag, which
    has no entry for a BYO box's Linux hostname and would 503 the
    student's /api/request_vm with 'no EC2 instance found'."""
    with vms_full_schema._cursor as cur:
        cur.execute("DELETE FROM vms WHERE hostname = 'ip-172-31-37-226'")
        cur.execute(
            "INSERT INTO vms "
            "(hostname, status, useremail, provider, endpoint_url, "
            " provider_metadata) "
            "VALUES ('ip-172-31-37-226', 'running', 'hep003@ucsd.edu', "
            "        'manual', 'http://172.31.37.226:7070', "
            "        '{\"lan_ip\": \"172.31.37.226\"}'::jsonb)"
        )

    from lablink_allocator_service.client_session import (
        prepare_browser_session,
    )

    fallback_called = []

    def _failing_fallback(hostname):
        fallback_called.append(hostname)
        raise AssertionError("fallback_fn should not be called for BYO rows")

    with patch(
        "lablink_allocator_service.client_session.requests.post"
    ) as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200, raise_for_status=lambda: None
        )
        prepare_browser_session(
            database=vms_full_schema,
            hostname="ip-172-31-37-226",
            session_id=uuid.uuid4(),
            browser_token="byo-tok",
            agent_token=AGENT_TOKEN,
            fallback_fn=_failing_fallback,
        )

    # Stored LAN IP wins: rotation targets it and fallback resolver is never called.
    assert fallback_called == []
    assert mock_post.call_args[0][0] == (
        "http://172.31.37.226:7070/api/session/start"
    )

    with vms_full_schema._cursor as cur:
        cur.execute(
            "SELECT upstream, browser_ws_url FROM vms "
            "WHERE hostname = 'ip-172-31-37-226'"
        )
        row = cur.fetchone()
    # Same allocator-proxied shape as AWS-managed rows so /desktop and
    # /internal/proxy_auth handle BYO and AWS uniformly.
    assert row[0] == "172.31.37.226:6080"
    assert row[1] == "proxy/byo-tok"


def test_browser_session_target_new_shape():
    from lablink_allocator_service.client_session import BrowserSessionTarget
    t = BrowserSessionTarget(ws_url="ws://x:6080", browser_credential="pw")
    assert t.ws_url == "ws://x:6080"
    assert t.browser_credential == "pw"
    t2 = BrowserSessionTarget(ws_url="proxy/abc", browser_credential=None)
    assert t2.browser_credential is None


def test_raises_when_instance_id_not_found(vms_full_schema):
    with vms_full_schema._cursor as cur:
        cur.execute("DELETE FROM vms WHERE hostname = 'ghost-host'")
        cur.execute(
            "INSERT INTO vms (hostname, status) "
            "VALUES ('ghost-host', 'running')"
        )

    from lablink_allocator_service.client_session import (
        RotationFailed,
        prepare_browser_session,
    )

    # Simulate a fallback resolver that cannot find the instance (e.g. EC2
    # Name-tag lookup returns None).  The fallback is responsible for raising
    # RotationFailed; client_session just propagates it.
    def _not_found(hostname):
        raise RotationFailed(f"no EC2 instance found for hostname {hostname}")

    with pytest.raises(RotationFailed):
        prepare_browser_session(
            database=vms_full_schema,
            hostname="ghost-host",
            session_id=uuid.uuid4(),
            browser_token="t",
            agent_token=AGENT_TOKEN,
            fallback_fn=_not_found,
        )
