import uuid
from unittest.mock import MagicMock, patch

import pytest
import requests


# Per-test API_TOKEN that matches what main.API_TOKEN would generate
# in production; passed explicitly to prepare_browser_session.
API_TOKEN = "test-api-token"


def test_happy_path_rotates_and_persists(real_db):
    """prepare_browser_session: rotates VNC password on the agent and
    updates the per-session columns on the clients row."""
    # Set up the table with the per-session columns the production schema has
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
            "ADD COLUMN IF NOT EXISTS sessionstartedat TIMESTAMPTZ"
        )
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
        "lablink_allocator_service.client_session.get_instance_id_by_name",
        return_value="i-abc",
    ), patch(
        "lablink_allocator_service.client_session.get_instance_private_ip",
        return_value="10.0.0.5",
    ), patch(
        "lablink_allocator_service.client_session.requests.post"
    ) as mock_post:
        mock_post.return_value = MagicMock(
            status_code=200, raise_for_status=lambda: None
        )
        target = prepare_browser_session(
            database=real_db,
            hostname="host-task10",
            session_id=session_id,
            browser_token="tok-abc",
            agent_token=API_TOKEN,
        )

    # Agent POST: correct URL, Bearer header sourced from agent_token kwarg,
    # body carries only the rotated password (the agent doesn't need
    # session_id or browser_token — those are allocator-side bookkeeping).
    mock_post.assert_called_once()
    url = mock_post.call_args[0][0]
    kwargs = mock_post.call_args[1]
    assert url == "http://10.0.0.5:7070/api/session/start"
    assert kwargs["headers"]["Authorization"] == f"Bearer {API_TOKEN}"
    assert "password" in kwargs["json"]
    assert kwargs["json"].keys() == {"password"}

    # Row updated with per-session columns. The password matches what we
    # sent on the wire, so /internal/proxy_auth's later lookup will yield
    # the same value the client agent installed.
    with real_db._cursor as cur:
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


def test_one_retry_then_raises(real_db):
    with real_db._cursor as cur:
        cur.execute(
            "ALTER TABLE vms "
            "ADD COLUMN IF NOT EXISTS status TEXT, "
            "ADD COLUMN IF NOT EXISTS useremail TEXT, "
            "ADD COLUMN IF NOT EXISTS sessionid UUID, "
            "ADD COLUMN IF NOT EXISTS browsertoken TEXT, "
            "ADD COLUMN IF NOT EXISTS vncpassword TEXT, "
            "ADD COLUMN IF NOT EXISTS upstream TEXT, "
            "ADD COLUMN IF NOT EXISTS sessionstartedat TIMESTAMPTZ"
        )
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
        "lablink_allocator_service.client_session.get_instance_id_by_name",
        return_value="i-abc",
    ), patch(
        "lablink_allocator_service.client_session.get_instance_private_ip",
        return_value="10.0.0.5",
    ), patch(
        "lablink_allocator_service.client_session.requests.post",
        side_effect=requests.RequestException("boom"),
    ) as mock_post:
        with pytest.raises(RotationFailed):
            prepare_browser_session(
                database=real_db,
                hostname="host-task10-fail",
                session_id=uuid.uuid4(),
                browser_token="t",
                agent_token=API_TOKEN,
            )

    assert mock_post.call_count == 2  # initial + one retry


def test_prepare_browser_session_persists_render_columns(monkeypatch):
    import lablink_allocator_service.client_session as cs
    import uuid

    monkeypatch.setattr(cs, "_lookup_private_ip", lambda h: "10.0.0.5")
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


def test_browser_session_target_new_shape():
    from lablink_allocator_service.client_session import BrowserSessionTarget
    t = BrowserSessionTarget(ws_url="ws://x:6080", browser_credential="pw")
    assert t.ws_url == "ws://x:6080"
    assert t.browser_credential == "pw"
    t2 = BrowserSessionTarget(ws_url="proxy/abc", browser_credential=None)
    assert t2.browser_credential is None


def test_raises_when_instance_id_not_found(real_db):
    with real_db._cursor as cur:
        cur.execute(
            "ALTER TABLE vms "
            "ADD COLUMN IF NOT EXISTS status TEXT, "
            "ADD COLUMN IF NOT EXISTS useremail TEXT"
        )
        cur.execute("DELETE FROM vms WHERE hostname = 'ghost-host'")
        cur.execute(
            "INSERT INTO vms (hostname, status) "
            "VALUES ('ghost-host', 'running')"
        )

    from lablink_allocator_service.client_session import (
        RotationFailed,
        prepare_browser_session,
    )

    with patch(
        "lablink_allocator_service.client_session.get_instance_id_by_name",
        return_value=None,
    ):
        with pytest.raises(RotationFailed):
            prepare_browser_session(
                database=real_db,
                hostname="ghost-host",
                session_id=uuid.uuid4(),
                browser_token="t",
                agent_token=API_TOKEN,
            )
