"""Process sampler — argv pattern matching against /proc/*/cmdline."""

import pytest

from lablink_client_service.monitoring.samplers import processes


@pytest.fixture
def allowlist():
    return ["sleap-train", "sleap-track", "sleap-label"]


def _write_cmdline(proc_dir, argv):
    """Write a NUL-separated /proc/<pid>/cmdline payload."""
    proc_dir.mkdir(parents=True, exist_ok=True)
    (proc_dir / "cmdline").write_bytes(b"\x00".join(a.encode() for a in argv) + b"\x00")


def test_direct_entry_point_script(tmp_path, allowlist):
    """`/opt/conda/bin/sleap-label` — the GUI binary itself."""
    _write_cmdline(tmp_path / "100", ["/opt/conda/bin/sleap-label"])
    seen = processes.sample(allowlist=allowlist, proc_root=str(tmp_path))
    assert seen == {"sleap-label"}


def test_sleap_subcommand_inference(tmp_path, allowlist):
    """`sleap track …` — GUI inference path (runners.py:541)."""
    _write_cmdline(
        tmp_path / "200",
        ["/opt/conda/bin/sleap", "track", "--gui", "--data_path", "x.slp"],
    )
    seen = processes.sample(allowlist=allowlist, proc_root=str(tmp_path))
    assert seen == {"sleap-track"}


def test_python_m_sleap_cli_training(tmp_path, allowlist):
    """`python -m sleap.cli train …` — GUI training path (runners.py:1311)."""
    _write_cmdline(
        tmp_path / "300",
        [
            "/opt/conda/bin/python",
            "-m",
            "sleap.cli",
            "train",
            "--config-name",
            "x",
        ],
    )
    seen = processes.sample(allowlist=allowlist, proc_root=str(tmp_path))
    assert seen == {"sleap-train"}


def test_python3_variant_matches(tmp_path, allowlist):
    """argv0 basename `python3.11` (not bare `python`) still matches."""
    _write_cmdline(
        tmp_path / "400",
        ["/usr/bin/python3.11", "-m", "sleap.cli", "track", "--data_path", "x.slp"],
    )
    seen = processes.sample(allowlist=allowlist, proc_root=str(tmp_path))
    assert seen == {"sleap-track"}


def test_ignores_non_allowlisted(tmp_path, allowlist):
    """Bash, random python, and unrelated `sleap-something` are ignored."""
    _write_cmdline(tmp_path / "100", ["/bin/bash", "-l"])
    _write_cmdline(tmp_path / "200", ["/opt/conda/bin/python", "script.py"])
    _write_cmdline(tmp_path / "300", ["/opt/conda/bin/sleap-render", "video.mp4"])
    seen = processes.sample(allowlist=allowlist, proc_root=str(tmp_path))
    assert seen == set()


def test_python_without_dash_m_does_not_match(tmp_path, allowlist):
    """`python sleap.cli train` (no -m) must not falsely match."""
    _write_cmdline(
        tmp_path / "100",
        ["/opt/conda/bin/python", "sleap.cli", "train"],
    )
    seen = processes.sample(allowlist=allowlist, proc_root=str(tmp_path))
    assert seen == set()


def test_sleap_with_unknown_subcommand_does_not_match(tmp_path, allowlist):
    """`sleap render …` is a real CLI but not in the allowlist."""
    _write_cmdline(tmp_path / "100", ["/opt/conda/bin/sleap", "render", "video.mp4"])
    seen = processes.sample(allowlist=allowlist, proc_root=str(tmp_path))
    assert seen == set()


def test_returns_empty_when_proc_missing(allowlist):
    assert (
        processes.sample(allowlist=allowlist, proc_root="/nonexistent") == set()
    )


def test_skips_unreadable_cmdline(tmp_path, allowlist):
    _write_cmdline(tmp_path / "100", ["/opt/conda/bin/sleap-label"])
    # No cmdline file under pid 200 — emulates a process that died mid-scan.
    (tmp_path / "200").mkdir()
    seen = processes.sample(allowlist=allowlist, proc_root=str(tmp_path))
    assert seen == {"sleap-label"}


def test_skips_kernel_threads_with_empty_cmdline(tmp_path, allowlist):
    """Kernel threads have empty cmdline; sampler must not crash on them."""
    (tmp_path / "100").mkdir()
    (tmp_path / "100" / "cmdline").write_bytes(b"")
    _write_cmdline(tmp_path / "200", ["/opt/conda/bin/sleap-label"])
    seen = processes.sample(allowlist=allowlist, proc_root=str(tmp_path))
    assert seen == {"sleap-label"}


def test_skips_non_numeric_entries(tmp_path, allowlist):
    """/proc has `self`, `thread-self`, etc. that aren't pids."""
    _write_cmdline(tmp_path / "self", ["/opt/conda/bin/sleap-train"])
    _write_cmdline(tmp_path / "100", ["/opt/conda/bin/sleap-label"])
    seen = processes.sample(allowlist=allowlist, proc_root=str(tmp_path))
    assert seen == {"sleap-label"}


def test_early_break_when_all_seen(tmp_path, allowlist):
    """Once every allowlist entry is matched, scanning stops."""
    _write_cmdline(tmp_path / "100", ["/opt/conda/bin/sleap-label"])
    _write_cmdline(tmp_path / "200", ["/opt/conda/bin/sleap-train"])
    _write_cmdline(tmp_path / "300", ["/opt/conda/bin/sleap-track"])
    seen = processes.sample(allowlist=allowlist, proc_root=str(tmp_path))
    assert seen == {"sleap-label", "sleap-train", "sleap-track"}
