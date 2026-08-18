"""Pusher — payload shape, headers, exception swallowing."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from lablink_client_service.monitoring.aggregator import new_counters
from lablink_client_service.monitoring.pusher import push_summary


def _counters():
    c = new_counters(datetime(2026, 6, 5, 17, 0, 0, tzinfo=timezone.utc))
    c.sample_count = 30
    c.seconds_in_subject_software = 60
    return c


def test_push_summary_posts_expected_payload():
    fake_resp = MagicMock(status_code=200, text="")
    with patch(
        "lablink_client_service.monitoring.pusher.requests.post",
        return_value=fake_resp,
    ) as mock_post:
        push_summary(
            allocator_url="https://alloc.example",
            hostname="vm-1",
            client_secret="s3cret",
            counters=_counters(),
        )
    mock_post.assert_called_once()
    call = mock_post.call_args
    assert call.kwargs["url"].endswith("/api/session-metrics/vm-1")
    body = call.kwargs["json"]
    assert body["session_started_at"].startswith("2026-06-05T17:00:00")
    assert body["counters"]["seconds_in_subject_software"] == 60
    headers = call.kwargs["headers"]
    assert headers["Authorization"] == "Bearer s3cret"


def test_push_summary_swallows_network_error():
    import requests as req

    with patch(
        "lablink_client_service.monitoring.pusher.requests.post",
        side_effect=req.exceptions.ConnectionError(),
    ):
        # Must not raise.
        push_summary(
            allocator_url="https://alloc.example",
            hostname="vm-1",
            client_secret="s3cret",
            counters=_counters(),
        )


def test_push_summary_logs_warning_on_4xx(caplog):
    import logging

    fake_resp = MagicMock(status_code=409, text="sealed")
    with patch(
        "lablink_client_service.monitoring.pusher.requests.post",
        return_value=fake_resp,
    ), caplog.at_level(logging.WARNING):
        rc = push_summary(
            allocator_url="https://alloc.example",
            hostname="vm-1",
            client_secret="s3cret",
            counters=_counters(),
        )
    assert rc == 409
    assert any("409" in rec.message for rec in caplog.records)


def test_push_summary_adopts_echoed_anchor(tmp_path, monkeypatch):
    from lablink_client_service.session_anchor import read_anchor

    anchor = tmp_path / "anchor"
    monkeypatch.setenv("LABLINK_SESSION_ANCHOR_PATH", str(anchor))
    fake_resp = MagicMock(status_code=200, text="")
    fake_resp.json.return_value = {
        "message": "Session metrics updated.",
        "session_started_at": "2026-06-11T15:21:13.459805+00:00",
    }
    with patch(
        "lablink_client_service.monitoring.pusher.requests.post",
        return_value=fake_resp,
    ):
        rc = push_summary(
            allocator_url="https://alloc.example",
            hostname="vm-1",
            client_secret="s3cret",
            counters=_counters(),
        )
    assert rc == 200
    assert read_anchor() == datetime(
        2026, 6, 11, 15, 21, 13, 459805, tzinfo=timezone.utc
    )


def test_push_summary_ignores_null_or_bad_echo(tmp_path, monkeypatch):
    anchor = tmp_path / "anchor"
    monkeypatch.setenv("LABLINK_SESSION_ANCHOR_PATH", str(anchor))
    for echoed in (None, "not-a-timestamp", 42):
        fake_resp = MagicMock(status_code=200, text="")
        fake_resp.json.return_value = {"session_started_at": echoed}
        with patch(
            "lablink_client_service.monitoring.pusher.requests.post",
            return_value=fake_resp,
        ):
            push_summary(
                allocator_url="https://alloc.example",
                hostname="vm-1",
                client_secret="s3cret",
                counters=_counters(),
            )
    assert not anchor.exists()
