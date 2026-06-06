"""Process sampler — allowlist matching against /proc/*/comm."""

import pytest

from lablink_client_service.monitoring.samplers import processes


@pytest.fixture
def allowlist():
    return ["sleap-train", "sleap-track", "sleap-label"]


def test_sample_returns_only_allowlisted_matches(tmp_path, allowlist):
    (tmp_path / "100").mkdir()
    (tmp_path / "100" / "comm").write_text("sleap-train\n")
    (tmp_path / "200").mkdir()
    (tmp_path / "200" / "comm").write_text("bash\n")
    (tmp_path / "300").mkdir()
    (tmp_path / "300" / "comm").write_text("sleap-label\n")
    (tmp_path / "self").mkdir()
    (tmp_path / "self" / "comm").write_text("ignored\n")

    seen = processes.sample(allowlist=allowlist, proc_root=str(tmp_path))
    assert seen == {"sleap-train", "sleap-label"}


def test_sample_returns_empty_when_proc_missing(allowlist):
    seen = processes.sample(allowlist=allowlist, proc_root="/nonexistent")
    assert seen == set()


def test_sample_skips_unreadable_comm(tmp_path, allowlist):
    (tmp_path / "100").mkdir()
    (tmp_path / "100" / "comm").write_text("sleap-train\n")
    (tmp_path / "200").mkdir()
    # No `comm` file under pid 200 — emulates a process that died mid-scan.
    seen = processes.sample(allowlist=allowlist, proc_root=str(tmp_path))
    assert seen == {"sleap-train"}
