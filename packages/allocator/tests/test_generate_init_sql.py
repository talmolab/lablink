"""Tests for generate_init_sql — schema invariants."""

from unittest.mock import patch, mock_open, MagicMock


def test_vm_table_includes_heartbeat_columns(monkeypatch):
    """The VM table schema must declare the heartbeat-tracking columns."""
    mock_config = MagicMock()
    mock_config.db.dbname = "d"
    mock_config.db.user = "u"
    mock_config.db.password = "p"
    mock_config.db.table_name = "vms"

    monkeypatch.setattr(
        "lablink_allocator_service.generate_init_sql.get_config",
        lambda: mock_config,
    )

    from lablink_allocator_service.generate_init_sql import main

    m = mock_open()
    with patch("builtins.open", m):
        main()

    handle = m()
    written = "".join(
        call.args[0] for call in handle.write.call_args_list
    )
    # Columns must be declared in lowercase-with-underscores so Postgres
    # stores them as `last_seen_at` etc. — queries throughout database.py
    # reference them that way. CamelCase names (e.g. `LastSeenAt`) would
    # be folded to `lastseenat`, breaking every query.
    for col in [
        "last_seen_at",
        "boot_id",
        "disk_free_pct",
    ]:
        assert col in written


def test_vm_table_includes_v2_assignment_columns(monkeypatch):
    """v2 routing fields: publichost (browser redirect target) and
    privateip (allocator -> agent /api/session/start)."""
    mock_config = MagicMock()
    mock_config.db.dbname = "d"
    mock_config.db.user = "u"
    mock_config.db.password = "p"
    mock_config.db.table_name = "vms"

    monkeypatch.setattr(
        "lablink_allocator_service.generate_init_sql.get_config",
        lambda: mock_config,
    )

    from lablink_allocator_service.generate_init_sql import main

    m = mock_open()
    with patch("builtins.open", m):
        main()

    handle = m()
    written = "".join(
        call.args[0] for call in handle.write.call_args_list
    )
    assert "PublicHost" in written
    assert "PrivateIp" in written


def test_vm_table_omits_crd_columns(monkeypatch):
    """CRD path is gone in v2 — schema must not declare its columns."""
    mock_config = MagicMock()
    mock_config.db.dbname = "d"
    mock_config.db.user = "u"
    mock_config.db.password = "p"
    mock_config.db.table_name = "vms"

    monkeypatch.setattr(
        "lablink_allocator_service.generate_init_sql.get_config",
        lambda: mock_config,
    )

    from lablink_allocator_service.generate_init_sql import main

    m = mock_open()
    with patch("builtins.open", m):
        main()

    handle = m()
    written = "".join(
        call.args[0] for call in handle.write.call_args_list
    )
    # Pin and CrdCommand columns existed pre-v2 alongside their
    # pg_notify trigger; all three are gone in v2.
    assert "Pin" not in written
    assert "CrdCommand" not in written
    assert "crd_active" not in written
    assert "notify_crd_command_update" not in written
