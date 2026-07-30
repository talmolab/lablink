"""Unit tests for relay_manager: per-client frpc-visitor subprocess
lifecycle + frps liveness check."""
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
            auth_token="ctl-token",
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
    """A live visitor whose on-disk config already matches is left alone."""
    from lablink_allocator_service import relay_manager

    monkeypatch.setattr(relay_manager, "VISITOR_CONFIG_DIR", tmp_path)
    args = dict(
        client_id="vm-1", alias_octet=12, secret_key="sek",
        server_addr="a", server_port=7000, auth_token="ctl-token",
    )
    # The config a previous call would have written for these exact args.
    (tmp_path / "vm-1.toml").write_text(relay_manager._visitor_config_toml(**args))
    running_proc = MagicMock()
    running_proc.poll.return_value = None  # still running
    monkeypatch.setattr(relay_manager, "_visitors", {"vm-1": running_proc})

    with patch(
        "lablink_allocator_service.relay_manager.subprocess.Popen"
    ) as mock_popen:
        relay_manager.start_visitor(**args)
    mock_popen.assert_not_called()


def test_start_visitor_replaces_live_visitor_when_secret_changed(
    tmp_path, monkeypatch
):
    """Re-registration mints a NEW secret and alias octet (see
    register_client), so a live visitor holding the previous pairing must be
    replaced, not kept. Observed live 2026-07-30: the stale visitor kept
    listening on the old alias with the old secret, frps answered
    `visitor connection ... auth failed`, and every health signal still
    reported the client as fine."""
    from lablink_allocator_service import relay_manager

    monkeypatch.setattr(relay_manager, "VISITOR_CONFIG_DIR", tmp_path)
    old = dict(
        client_id="vm-1", alias_octet=10, secret_key="old-secret",
        server_addr="a", server_port=7000, auth_token="ctl-token",
    )
    (tmp_path / "vm-1.toml").write_text(relay_manager._visitor_config_toml(**old))
    running_proc = MagicMock()
    running_proc.poll.return_value = None  # still running
    monkeypatch.setattr(relay_manager, "_visitors", {"vm-1": running_proc})

    with patch(
        "lablink_allocator_service.relay_manager.subprocess.Popen"
    ) as mock_popen:
        relay_manager.start_visitor(**{**old, "alias_octet": 11,
                                      "secret_key": "new-secret"})

    mock_popen.assert_called_once()
    running_proc.terminate.assert_called_once()
    content = (tmp_path / "vm-1.toml").read_text()
    assert 'secretKey = "new-secret"' in content
    assert 'bindAddr = "127.0.0.11"' in content
    assert "old-secret" not in content


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
            server_addr="a", server_port=7000, auth_token="ctl-token",
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
                server_addr="h", server_port=7000, auth_token="ctl-token",
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
            server_addr="h", server_port=7000, auth_token="ctl-token",
        )

    assert (conf_dir / "vm-1.toml").stat().st_mode & 0o777 == 0o600
    assert conf_dir.stat().st_mode & 0o777 == 0o700


def test_visitor_config_escapes_string_values():
    """Every interpolated string must be emitted as an escaped TOML basic
    string, so a stray quote or newline in operator-supplied config can't
    terminate the string and inject a key.

    Asserted on the rendered text rather than via a TOML parser: tomllib is
    3.11+, and this package supports Python 3.10 (CI runs 3.10)."""
    from lablink_allocator_service import relay_manager

    injected = 'vm"\nbindPort = 22'
    toml = relay_manager._visitor_config_toml(
        client_id="vm-1", alias_octet=12, secret_key='se"k',
        server_addr=injected, server_port=7000, auth_token="ctl-token",
    )

    # The quote is backslash-escaped, and the newline is the two-character
    # escape rather than a real line break.
    assert 'secretKey = "se\\"k"' in toml
    assert "\\n" in toml
    assert injected not in toml

    # The decisive property: the injected text cannot become a key.
    assert not any(
        line.strip().startswith("bindPort = 22") for line in toml.splitlines()
    )

    # Structure is fixed regardless of input: 3 header lines (serverAddr,
    # serverPort, auth.token) + 2 blocks of 7 keys each, separated by blanks.
    assert len(toml.splitlines()) == 19


def test_visitor_config_shape_for_normal_input():
    """Structural check without a TOML parser (see the note above): every
    non-blank line is either a table header or a single key = value."""
    from lablink_allocator_service import relay_manager

    toml = relay_manager._visitor_config_toml(
        client_id="classroom-gpu-3", alias_octet=10, secret_key="s3cret",
        server_addr="allocator.example.com", server_port=7000,
            auth_token="ctl-token",
    )

    assert 'serverName = "classroom-gpu-3-kasmvnc"' in toml
    assert 'serverName = "classroom-gpu-3-agent"' in toml
    assert 'serverAddr = "allocator.example.com"' in toml
    assert "serverPort = 7000" in toml
    assert 'bindAddr = "127.0.0.10"' in toml
    assert toml.count("[[visitors]]") == 2

    for line in (ln for ln in toml.splitlines() if ln.strip()):
        assert line == "[[visitors]]" or " = " in line, f"malformed line: {line!r}"


def test_visitor_config_carries_the_control_plane_auth_token():
    """Regression guard for a showstopper found only by hand-testing: the
    allocator's own visitor is an frpc client, so it must present the
    deployment's auth.token. Without it frps rejects the login with "token
    in login doesn't match token from configuration" and frpc exits at
    once (loginFailExit defaults on), leaving every relay client
    unreachable while registration still returns a healthy 200. Mocked
    Popen means no unit test can observe the exit -- so assert the config
    key directly."""
    from lablink_allocator_service import relay_manager

    toml = relay_manager._visitor_config_toml(
        client_id="vm-1", alias_octet=12, secret_key="sek",
        server_addr="h", server_port=7000, auth_token="ctl-token",
    )
    assert 'auth.token = "ctl-token"' in toml


def test_visitor_config_escapes_the_auth_token():
    from lablink_allocator_service import relay_manager

    toml = relay_manager._visitor_config_toml(
        client_id="vm-1", alias_octet=12, secret_key="sek",
        server_addr="h", server_port=7000, auth_token='tok"en',
    )
    assert 'auth.token = "tok\\"en"' in toml


def test_start_visitor_requires_an_auth_token_argument():
    """Keyword is required, not defaulted: a default would let a caller
    silently omit it and reproduce the original outage."""
    import inspect
    from lablink_allocator_service import relay_manager

    param = inspect.signature(relay_manager.start_visitor).parameters["auth_token"]
    assert param.default is inspect.Parameter.empty
