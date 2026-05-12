import uuid
from unittest.mock import MagicMock, patch

import pytest
import requests


@pytest.fixture(autouse=True)
def register_token_env(monkeypatch):
    monkeypatch.setenv("REGISTER_TOKEN", "rt-secret")


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
        )

    # Agent POST: correct URL, Bearer header, body shape
    mock_post.assert_called_once()
    url = mock_post.call_args[0][0]
    kwargs = mock_post.call_args[1]
    assert url == "http://10.0.0.5:7070/api/session/start"
    assert kwargs["headers"]["Authorization"] == "Bearer rt-secret"
    assert kwargs["json"]["browser_token"] == "tok-abc"
    assert "vnc_password" in kwargs["json"]

    # Row updated with per-session columns
    with real_db._cursor as cur:
        cur.execute(
            "SELECT sessionid, browsertoken, vncpassword, upstream "
            "FROM vms WHERE hostname = 'host-task10'"
        )
        row = cur.fetchone()
    assert str(row[0]) == str(session_id)
    assert row[1] == "tok-abc"
    assert row[2] == kwargs["json"]["vnc_password"]
    assert row[3] == "10.0.0.5:6080"
    assert target.upstream == "10.0.0.5:6080"


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
            )

    assert mock_post.call_count == 2  # initial + one retry


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
            )
