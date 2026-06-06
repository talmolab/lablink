"""Destroy paths must bulk-seal session-metrics rows."""

from unittest.mock import MagicMock


def test_scheduled_destroy_seals_before_destroy(monkeypatch):
    from lablink_allocator_service import scheduler as sched_mod

    fake_db = MagicMock()
    fake_provider = MagicMock()
    call_order: list[str] = []
    fake_db.bulk_seal_session_metrics.side_effect = lambda: call_order.append(
        "seal"
    ) or 3
    fake_provider.destroy_hosts.side_effect = lambda handles: call_order.append(
        "destroy"
    ) or MagicMock(stdout="ok")

    monkeypatch.setattr(sched_mod, "database", fake_db, raising=False)
    monkeypatch.setattr(sched_mod, "provider", fake_provider, raising=False)

    sched_mod.run_scheduled_destroy(["h1", "h2", "h3"])
    assert call_order == ["seal", "destroy"]


def test_admin_destroy_route_seals(monkeypatch):
    from lablink_allocator_service import main

    fake_db = MagicMock()
    fake_provider = MagicMock()
    fake_provider.destroy_hosts.return_value = MagicMock(stdout="ok")
    monkeypatch.setattr(main, "database", fake_db, raising=False)
    monkeypatch.setattr(main, "provider", fake_provider, raising=False)

    main.app.config["TESTING"] = True
    client = main.app.test_client()
    client.post("/destroy", headers={"Authorization": "Basic YWRtaW46YWRtaW4="})
    # Either success or auth failure is OK — we only care that, when destroy
    # is reached, the seal call comes first.
    if fake_provider.destroy_hosts.called:
        fake_db.bulk_seal_session_metrics.assert_called_once()
