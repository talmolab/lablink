"""Tests for the reverse-tunnel connectivity mode's server-side bookkeeping:
the per-client restrictions file and the attached-client check."""
import pytest


@pytest.fixture
def tm(tmp_path, monkeypatch):
    from lablink_allocator_service import tunnel_manager

    monkeypatch.setattr(
        tunnel_manager, "RESTRICTIONS_PATH", tmp_path / "restrictions.yaml"
    )
    monkeypatch.setattr(tunnel_manager, "_restrictions", {})
    return tunnel_manager


def test_path_prefix_is_stable_and_client_specific(tm):
    a = tm.path_prefix("vm-1", "secret-a")
    assert a == tm.path_prefix("vm-1", "secret-a")
    assert a != tm.path_prefix("vm-2", "secret-a")
    assert a != tm.path_prefix("vm-1", "secret-b")
    assert a.startswith("vm-1-")


def test_authorize_writes_a_rule_scoped_to_one_alias(tm):
    tm.authorize_client(client_id="vm-1", alias_octet=10, prefix="vm-1-abc")
    text = tm.RESTRICTIONS_PATH.read_text()
    assert "vm-1-abc" in text
    assert "127.0.0.10/32" in text
    assert "6080" in text and "7070" in text
    # The whole point: no other alias may appear in this client's rule.
    assert "127.0.0.11" not in text


def test_second_client_does_not_clobber_the_first(tm):
    tm.authorize_client(client_id="vm-1", alias_octet=10, prefix="vm-1-abc")
    tm.authorize_client(client_id="vm-2", alias_octet=11, prefix="vm-2-def")
    text = tm.RESTRICTIONS_PATH.read_text()
    assert "vm-1-abc" in text and "vm-2-def" in text


def test_revoke_removes_only_that_client(tm):
    tm.authorize_client(client_id="vm-1", alias_octet=10, prefix="vm-1-abc")
    tm.authorize_client(client_id="vm-2", alias_octet=11, prefix="vm-2-def")
    tm.revoke_client("vm-1")
    text = tm.RESTRICTIONS_PATH.read_text()
    assert "vm-1-abc" not in text
    assert "vm-2-def" in text


def test_revoke_unknown_client_is_a_noop(tm):
    tm.revoke_client("never-registered")  # must not raise


def test_restrictions_file_is_owner_only(tm):
    tm.authorize_client(client_id="vm-1", alias_octet=10, prefix="vm-1-abc")
    assert tm.RESTRICTIONS_PATH.stat().st_mode & 0o777 == 0o600


def test_attached_aliases_reads_listening_sockets(tm, monkeypatch):
    # 0A00007F:17C0 == 127.0.0.10:6080 in /proc/net/tcp's byte order.
    monkeypatch.setattr(
        tm, "_proc_net_tcp",
        lambda: "sl local_address rem_address st\n"
                " 0: 0A00007F:17C0 00000000:0000 0A\n",
    )
    assert tm.attached_aliases() == {10}


def test_attached_aliases_ignores_non_listening_rows(tm, monkeypatch):
    monkeypatch.setattr(
        tm, "_proc_net_tcp",
        lambda: "sl local_address rem_address st\n"
                " 0: 0A00007F:17C0 01020304:1F90 01\n",
    )
    assert tm.attached_aliases() == set()
