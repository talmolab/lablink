"""Tests for the reverse-tunnel connectivity mode's server-side bookkeeping:
the per-client restrictions file and the attached-client check."""
import pytest
import yaml


@pytest.fixture
def tm(tmp_path, monkeypatch):
    from lablink_allocator_service import tunnel_manager

    monkeypatch.setattr(
        tunnel_manager, "RESTRICTIONS_PATH", tmp_path / "restrictions.yaml"
    )
    monkeypatch.setattr(tunnel_manager, "_restrictions", {})
    monkeypatch.setattr(tunnel_manager, "_hydrated", False)
    return tunnel_manager


def test_path_prefix_is_stable_and_client_specific(tm):
    a = tm.path_prefix("vm-1", "secret-a")
    assert a == tm.path_prefix("vm-1", "secret-a")
    assert a != tm.path_prefix("vm-2", "secret-a")
    assert a != tm.path_prefix("vm-1", "secret-b")
    assert a.startswith("tun-vm-1-")


def test_authorize_writes_a_rule_scoped_to_one_alias(tm):
    tm.authorize_client(client_id="vm-1", alias_octet=10, prefix="tun-vm-1-abc")
    text = tm.RESTRICTIONS_PATH.read_text()
    assert "tun-vm-1-abc" in text
    assert "127.0.0.10/32" in text
    assert "6080" in text and "7070" in text
    # The whole point: no other alias may appear in this client's rule.
    assert "127.0.0.11" not in text


def test_match_value_has_no_path_separator(tm):
    # !PathPrefix matches only the client's first path segment (measured
    # against wstunnel 10.6.2). A match value with a "/" in it can never
    # fire -- and the failure mode is a silent deny-all for that client,
    # not an error, which is exactly how this went unnoticed the first
    # time. The rendered match must be the bare prefix.
    tm.authorize_client(client_id="vm-1", alias_octet=10, prefix="tun-vm-1-abc")
    parsed = yaml.safe_load(tm.RESTRICTIONS_PATH.read_text())
    match_value = parsed["restrictions"][0]["match"][0]
    assert "/" not in match_value
    assert match_value == "tun-vm-1-abc"


def test_second_client_does_not_clobber_the_first(tm):
    tm.authorize_client(client_id="vm-1", alias_octet=10, prefix="tun-vm-1-abc")
    tm.authorize_client(client_id="vm-2", alias_octet=11, prefix="tun-vm-2-def")
    text = tm.RESTRICTIONS_PATH.read_text()
    assert "tun-vm-1-abc" in text and "tun-vm-2-def" in text


def test_revoke_removes_only_that_client(tm):
    tm.authorize_client(client_id="vm-1", alias_octet=10, prefix="tun-vm-1-abc")
    tm.authorize_client(client_id="vm-2", alias_octet=11, prefix="tun-vm-2-def")
    tm.revoke_client("vm-1")
    text = tm.RESTRICTIONS_PATH.read_text()
    assert "tun-vm-1-abc" not in text
    assert "tun-vm-2-def" in text


def test_revoke_unknown_client_is_a_noop(tm):
    tm.revoke_client("never-registered")  # must not raise


@pytest.mark.parametrize("client_id,octet,prefix", [
    # A newline could forge a second top-level YAML restriction if it ever
    # reached the renderer; client_id is the DB hostname, so it arrives from
    # registration input. Trailing-newline cases specifically: `.match()` with
    # a `$`-anchored pattern still accepts them (Python's `$` matches before a
    # trailing newline), so fullmatch is what actually closes it.
    ("vm-evil\nrestrictions:\n  - name: pwn", 10, "tun-vm-evil-abc"),
    ("vm-1", 10, "vm-1\nrestrictions:"),
    ("vm-1\n", 10, "tun-vm-1-abc"),
    ("vm-1", 10, "tun-vm-1-abc\n"),
    ("vm-1", 255, "tun-vm-1-abc"),   # octet range: above
    ("vm-1", 0, "tun-vm-1-abc"),     # ...and below
])
def test_authorize_rejects_unsafe_input(tm, client_id, octet, prefix):
    with pytest.raises(ValueError):
        tm.authorize_client(client_id=client_id, alias_octet=octet, prefix=prefix)
    assert not tm.RESTRICTIONS_PATH.exists()


def test_render_cannot_be_forced_into_a_second_top_level_entry(tm):
    # Defense in depth, independent of authorize_client's validation: even
    # if a malicious value reached the module-level dict directly, the
    # yaml.safe_dump-based renderer must not let it forge extra YAML
    # structure. Pokes the private dict the same way the `tm` fixture does.
    evil_client_id = "vm-evil\nrestrictions:\n  - name: pwn\n    match: [!Any]"
    tm._restrictions[evil_client_id] = (10, "whatever")
    tm._write()
    parsed = yaml.safe_load(tm.RESTRICTIONS_PATH.read_text())
    assert len(parsed["restrictions"]) == 1
    assert parsed["restrictions"][0]["name"] == evil_client_id


def test_restrictions_file_is_owner_only(tm):
    tm.authorize_client(client_id="vm-1", alias_octet=10, prefix="tun-vm-1-abc")
    assert tm.RESTRICTIONS_PATH.stat().st_mode & 0o777 == 0o600


def test_authorize_after_restart_does_not_drop_other_clients(tm):
    """A bare allocator restart wipes the in-process _restrictions dict
    (module-level, not persisted) but leaves the restrictions file on
    disk. Without rehydration, the next authorize_client() renders the
    WHOLE file from the empty dict, silently revoking every other
    client's tunnel."""
    tm.authorize_client(client_id="vm-1", alias_octet=10, prefix="tun-vm-1-abc")
    tm.authorize_client(client_id="vm-2", alias_octet=11, prefix="tun-vm-2-def")

    # Simulate a process restart: the dict and the hydration flag are
    # gone; the file (RESTRICTIONS_PATH, patched by the fixture) survives.
    tm._restrictions.clear()
    tm._hydrated = False

    tm.authorize_client(client_id="vm-3", alias_octet=12, prefix="tun-vm-3-ghi")

    text = tm.RESTRICTIONS_PATH.read_text()
    assert "tun-vm-1-abc" in text
    assert "tun-vm-2-def" in text
    assert "tun-vm-3-ghi" in text


def test_revoke_after_restart_finds_the_stale_entry(tm):
    """revoke_client must also rehydrate: otherwise a revoke issued right
    after a restart (before any authorize_client call) is a no-op against
    the empty in-memory dict, leaving the stale rule live forever."""
    tm.authorize_client(client_id="vm-1", alias_octet=10, prefix="tun-vm-1-abc")
    tm._restrictions.clear()
    tm._hydrated = False

    tm.revoke_client("vm-1")

    text = tm.RESTRICTIONS_PATH.read_text()
    assert "tun-vm-1-abc" not in text


def test_hydrate_tolerates_a_malformed_file(tm):
    tm.RESTRICTIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tm.RESTRICTIONS_PATH.write_text("not: [valid")  # unterminated flow sequence
    tm.authorize_client(client_id="vm-1", alias_octet=10, prefix="tun-vm-1-abc")
    text = tm.RESTRICTIONS_PATH.read_text()
    assert "tun-vm-1-abc" in text
    assert "not:" not in text


def test_hydrate_only_reads_the_file_once_per_process(tm):
    """A second hydrate call in the same process must be a no-op -- once
    _hydrated is set, an external rewrite of the file (another process, a
    human edit) must not get silently picked up mid-run."""
    tm.authorize_client(client_id="vm-1", alias_octet=10, prefix="tun-vm-1-abc")
    tm.RESTRICTIONS_PATH.write_text(
        "restrictions:\n"
        "- name: vm-9\n"
        "  match: [tun-vm-9-xyz]\n"
        "  allow:\n"
        "  - port: ['6080', '7070']\n"
        "    cidr: ['127.0.0.9/32']\n"
    )
    tm._hydrate_from_disk()
    assert "vm-9" not in tm._restrictions
    assert "vm-1" in tm._restrictions


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
