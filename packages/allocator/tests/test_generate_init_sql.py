"""Tests for generate_init_sql — in particular the trigger WHEN guard."""

from unittest.mock import patch, mock_open, MagicMock


def test_crd_command_trigger_has_when_guard(monkeypatch):
    """The notify trigger must only fire when CrdCommand is non-null.

    Without the WHEN guard, record_reboot and release_assignment (which
    set CrdCommand = NULL) produce NOTIFY payloads the LISTEN loop
    already discards, spamming "Invalid notification payload" warnings
    in every listening client.
    """
    mock_config = MagicMock()
    mock_config.db.dbname = "d"
    mock_config.db.user = "u"
    mock_config.db.password = "p"
    mock_config.db.table_name = "vms"
    mock_config.db.message_channel = "ch"

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
    assert "CREATE TRIGGER trigger_crd_command_insert_or_update" in written
    assert "WHEN (NEW.CrdCommand IS NOT NULL)" in written


def test_vm_table_includes_heartbeat_columns(monkeypatch):
    """The VM table schema must declare the five heartbeat columns."""
    mock_config = MagicMock()
    mock_config.db.dbname = "d"
    mock_config.db.user = "u"
    mock_config.db.password = "p"
    mock_config.db.table_name = "vms"
    mock_config.db.message_channel = "ch"

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
    for col in [
        "LastSeenAt",
        "BootId",
        "CrdActive",
        "DockerHealthy",
        "DiskFreePct",
    ]:
        assert col in written
