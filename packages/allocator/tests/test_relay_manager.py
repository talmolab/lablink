"""Unit tests for relay_manager: per-client frpc-visitor subprocess
lifecycle + frps liveness check."""
import tomllib
from unittest.mock import MagicMock, patch

import pytest


def test_start_visitor_writes_config_and_spawns_frpc(tmp_path, monkeypatch):
    from lablink_allocator_service import relay_manager

    monkeypatch.setattr(relay_manager, "VISITOR_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(relay_manager, "_visitors", {})

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    with patch(
        "lablink_allocator_service.relay_manager.subprocess.Popen",
        return_value=fake_proc,
    ) as mock_popen:
        relay_manager.start_visitor(
            client_id="vm-1", alias_octet=12, secret_key="sek",
            server_addr="allocator.example.com", server_port=7000,
        )

    config_path = tmp_path / "vm-1.toml"
    assert config_path.exists()
    content = config_path.read_text()
    assert 'bindAddr = "127.0.0.12"' in content
    assert "bindPort = 6080" in content
    assert "bindPort = 7070" in content
    assert 'secretKey = "sek"' in content
    assert 'serverAddr = "allocator.example.com"' in content
    assert "serverPort = 7000" in content
    mock_popen.assert_called_once_with(["frpc", "-c", str(config_path)])
    assert relay_manager._visitors["vm-1"] is fake_proc


def test_start_visitor_is_idempotent_when_already_running(tmp_path, monkeypatch):
    from lablink_allocator_service import relay_manager

    monkeypatch.setattr(relay_manager, "VISITOR_CONFIG_DIR", tmp_path)
    running_proc = MagicMock()
    running_proc.poll.return_value = None  # still running
    monkeypatch.setattr(relay_manager, "_visitors", {"vm-1": running_proc})

    with patch(
        "lablink_allocator_service.relay_manager.subprocess.Popen"
    ) as mock_popen:
        relay_manager.start_visitor(
            client_id="vm-1", alias_octet=12, secret_key="sek",
            server_addr="a", server_port=7000,
        )
    mock_popen.assert_not_called()


def test_start_visitor_respawns_when_tracked_process_is_dead(tmp_path, monkeypatch):
    """A visitor that crashed (poll() returns an exit code) must be
    replaced, not treated as still-running -- otherwise a re-registration
    after a crash silently leaves the client unreachable."""
    from lablink_allocator_service import relay_manager

    monkeypatch.setattr(relay_manager, "VISITOR_CONFIG_DIR", tmp_path)
    dead_proc = MagicMock()
    dead_proc.poll.return_value = 1  # exited
    monkeypatch.setattr(relay_manager, "_visitors", {"vm-1": dead_proc})

    new_proc = MagicMock()
    new_proc.poll.return_value = None
    with patch(
        "lablink_allocator_service.relay_manager.subprocess.Popen",
        return_value=new_proc,
    ) as mock_popen:
        relay_manager.start_visitor(
            client_id="vm-1", alias_octet=12, secret_key="sek",
            server_addr="a", server_port=7000,
        )
    mock_popen.assert_called_once()
    assert relay_manager._visitors["vm-1"] is new_proc


def test_stop_visitor_terminates_and_removes_config(tmp_path, monkeypatch):
    from lablink_allocator_service import relay_manager

    monkeypatch.setattr(relay_manager, "VISITOR_CONFIG_DIR", tmp_path)
    config_path = tmp_path / "vm-1.toml"
    config_path.write_text("stale config")

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    monkeypatch.setattr(relay_manager, "_visitors", {"vm-1": fake_proc})

    relay_manager.stop_visitor("vm-1")

    fake_proc.terminate.assert_called_once()
    fake_proc.wait.assert_called_once_with(timeout=5)
    assert not config_path.exists()
    assert "vm-1" not in relay_manager._visitors


def test_stop_visitor_is_noop_when_not_tracked(monkeypatch):
    from lablink_allocator_service import relay_manager

    monkeypatch.setattr(relay_manager, "_visitors", {})
    relay_manager.stop_visitor("unknown")  # must not raise


def test_frp_status_ok_when_port_reachable(monkeypatch):
    from lablink_allocator_service import relay_manager

    mock_cfg = type("Cfg", (), {"manual": type("M", (), {"frps_bind_port": 7000})()})()
    monkeypatch.setattr(relay_manager, "get_config", lambda: mock_cfg)
    with patch(
        "lablink_allocator_service.relay_manager.socket.create_connection"
    ) as mock_connect:
        mock_connect.return_value.__enter__ = MagicMock()
        mock_connect.return_value.__exit__ = MagicMock(return_value=False)
        assert relay_manager.frp_status() == "ok"


def test_frp_status_not_running_when_connection_refused(monkeypatch):
    from lablink_allocator_service import relay_manager

    mock_cfg = type("Cfg", (), {"manual": type("M", (), {"frps_bind_port": 7000})()})()
    monkeypatch.setattr(relay_manager, "get_config", lambda: mock_cfg)
    with patch(
        "lablink_allocator_service.relay_manager.socket.create_connection",
        side_effect=OSError("refused"),
    ):
        assert relay_manager.frp_status() == "not running"


# ---- hardening: client_id reaches a filesystem path and a config file ----

UNSAFE_CLIENT_IDS = [
    "../../etc/passwd",   # directory traversal
    "..",                 # traversal via bare dotdot
    "a/b",                # nested path
    "/abs",               # absolute path
    'x"y',                # TOML string terminator
    "x\ny",               # newline -> injected TOML line
    "",                   # empty
    "-leading-dash",      # must start alphanumeric
]


@pytest.mark.parametrize("bad", UNSAFE_CLIENT_IDS)
def test_start_visitor_rejects_unsafe_client_id(bad, tmp_path, monkeypatch):
    """client_id is interpolated into both a path and a config file, so
    relay_manager must refuse unsafe values on its own -- registration
    validates too, but this module must not depend on that."""
    from lablink_allocator_service import relay_manager

    monkeypatch.setattr(relay_manager, "VISITOR_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(relay_manager, "_visitors", {})

    with patch(
        "lablink_allocator_service.relay_manager.subprocess.Popen"
    ) as mock_popen:
        with pytest.raises(ValueError):
            relay_manager.start_visitor(
                client_id=bad, alias_octet=12, secret_key="sek",
                server_addr="h", server_port=7000,
            )
    mock_popen.assert_not_called()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("bad", UNSAFE_CLIENT_IDS)
def test_stop_visitor_ignores_unsafe_client_id_without_touching_fs(
    bad, tmp_path, monkeypatch,
):
    """stop_visitor runs unconditionally on every unregister, so an unsafe
    id must be a silent no-op rather than a raise (which would 500 the
    unregister) -- and must never unlink a path derived from it."""
    from lablink_allocator_service import relay_manager

    monkeypatch.setattr(relay_manager, "VISITOR_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(relay_manager, "_visitors", {})
    canary = tmp_path / "canary.toml"
    canary.write_text("do not delete")

    relay_manager.stop_visitor(bad)  # must not raise

    assert canary.exists()


def test_start_visitor_config_is_owner_readable_only(tmp_path, monkeypatch):
    """The visitor config embeds the per-client STCP secretKey in
    plaintext, so it must not be world-readable -- the CLI already writes
    registration secrets at 0600."""
    from lablink_allocator_service import relay_manager

    conf_dir = tmp_path / "visitors"
    monkeypatch.setattr(relay_manager, "VISITOR_CONFIG_DIR", conf_dir)
    monkeypatch.setattr(relay_manager, "_visitors", {})

    fake_proc = MagicMock()
    fake_proc.poll.return_value = None
    with patch(
        "lablink_allocator_service.relay_manager.subprocess.Popen",
        return_value=fake_proc,
    ):
        relay_manager.start_visitor(
            client_id="vm-1", alias_octet=12, secret_key="sek",
            server_addr="h", server_port=7000,
        )

    assert (conf_dir / "vm-1.toml").stat().st_mode & 0o777 == 0o600
    assert conf_dir.stat().st_mode & 0o777 == 0o700


def test_visitor_config_escapes_string_values():
    """Every interpolated string must be emitted as a properly escaped
    TOML basic string, so a stray quote in operator-supplied config can't
    corrupt the file."""
    from lablink_allocator_service import relay_manager

    toml = relay_manager._visitor_config_toml(
        client_id="vm-1", alias_octet=12, secret_key='se"k',
        server_addr='ho"st', server_port=7000,
    )
    parsed = tomllib.loads(toml)
    assert parsed["serverAddr"] == 'ho"st'
    assert parsed["serverPort"] == 7000
    assert parsed["visitors"][0]["secretKey"] == 'se"k'
    assert parsed["visitors"][0]["bindAddr"] == "127.0.0.12"
    assert [v["bindPort"] for v in parsed["visitors"]] == [6080, 7070]


def test_visitor_config_is_valid_toml_for_normal_input():
    from lablink_allocator_service import relay_manager

    toml = relay_manager._visitor_config_toml(
        client_id="classroom-gpu-3", alias_octet=10, secret_key="s3cret",
        server_addr="allocator.example.com", server_port=7000,
    )
    parsed = tomllib.loads(toml)
    assert parsed["visitors"][0]["serverName"] == "classroom-gpu-3-kasmvnc"
    assert parsed["visitors"][1]["serverName"] == "classroom-gpu-3-agent"
