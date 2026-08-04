"""Bounded reads of the allocator's own log file."""
import os

from lablink_allocator_service.utils.log_tail import (
    read_allocator_log,
    redact_secrets,
)


def test_tail_returns_last_n_lines(tmp_path):
    (tmp_path / "allocator.log").write_text(
        "\n".join(f"line {i}" for i in range(100)) + "\n"
    )
    out = read_allocator_log(log_dir=tmp_path, max_lines=10)
    assert out.splitlines() == [f"line {i}" for i in range(90, 100)]


def test_tail_spans_rotation_files_oldest_first(tmp_path):
    """`rotatelogs -n` cycles filenames, so the suffix does not indicate
    age -- ordering must come from mtime."""
    older = tmp_path / "allocator.log"
    newer = tmp_path / "allocator.log.1"
    older.write_text("from the older file\n")
    newer.write_text("from the newer file\n")
    os.utime(older, (1_000, 1_000))
    os.utime(newer, (2_000, 2_000))

    out = read_allocator_log(log_dir=tmp_path, max_lines=10)
    assert out.splitlines() == ["from the older file", "from the newer file"]


def test_missing_log_dir_returns_none(tmp_path):
    assert read_allocator_log(log_dir=tmp_path / "nope") is None


def test_empty_log_dir_returns_none(tmp_path):
    assert read_allocator_log(log_dir=tmp_path) is None


def test_redacts_secret_assignments():
    text = (
        "POSTGRES_PASSWORD=hunter2\n"
        "CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoiYWJj\n"
        "admin_password: s3cret\n"
        "Starting nginx on :5000...\n"
    )
    out = redact_secrets(text)
    assert "hunter2" not in out
    assert "eyJhIjoiYWJj" not in out
    assert "s3cret" not in out
    assert "Starting nginx on :5000..." in out
    assert out.count("***REDACTED***") == 3


def test_redaction_applies_through_read(tmp_path):
    (tmp_path / "allocator.log").write_text("DB_PASSWORD=letmein\n")
    out = read_allocator_log(log_dir=tmp_path)
    assert "letmein" not in out
    assert "***REDACTED***" in out
