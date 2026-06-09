"""Entry point — config loading + tick loop + SIGTERM flush."""

import json
import signal
import threading
import time
from unittest.mock import patch


def test_main_reads_config_file_and_starts_loop(tmp_path, monkeypatch):
    cfg_path = tmp_path / "monitoring.json"
    cfg_path.write_text(
        json.dumps(
            {
                "allocator_url": "https://alloc.example",
                "hostname": "vm-1",
                "client_secret": "s3cret",
                "client_software": "sleap",
                "subject_window_patterns": [],
                "process_allowlist": ["sleap-train"],
                "watch_dir": str(tmp_path),
                "sample_interval_seconds": 0,
                "push_interval_seconds": 0,
            }
        )
    )
    monkeypatch.setenv("LABLINK_MONITORING_CONFIG", str(cfg_path))

    from lablink_client_service.monitoring import __main__ as entry

    # Reset module state from any prior test.
    entry._stop_event.clear()
    entry._counters = None
    entry._cfg = {}

    pushed: list = []

    def fake_push(**kwargs):
        pushed.append(kwargs)
        if len(pushed) >= 2:
            entry._stop_event.set()
        return 200

    with (
        patch.object(entry, "push_summary", side_effect=fake_push),
        patch.object(entry, "_sample_active_window", return_value="subject"),
        patch.object(entry, "_sample_gpu", return_value=(50, 1000)),
        patch.object(entry, "_sample_processes", return_value=set()),
        patch.object(
            entry,
            "_sample_filesystem",
            return_value=(None, None, None),
        ),
    ):
        entry.main()

    assert len(pushed) >= 2
    assert pushed[-1]["counters"].seconds_in_subject_software > 0


def test_sigterm_triggers_final_flush(tmp_path, monkeypatch):
    cfg_path = tmp_path / "monitoring.json"
    cfg_path.write_text(
        json.dumps(
            {
                "allocator_url": "https://alloc.example",
                "hostname": "vm-1",
                "client_secret": "s3cret",
                "client_software": "sleap",
                "subject_window_patterns": [],
                "process_allowlist": [],
                "watch_dir": str(tmp_path),
                "sample_interval_seconds": 0,
                "push_interval_seconds": 60,
            }
        )
    )
    monkeypatch.setenv("LABLINK_MONITORING_CONFIG", str(cfg_path))

    from lablink_client_service.monitoring import __main__ as entry

    entry._stop_event.clear()
    entry._counters = None
    entry._cfg = {}

    pushed: list = []

    def fake_push(**kwargs):
        pushed.append(kwargs)
        return 200

    with (
        patch.object(entry, "push_summary", side_effect=fake_push),
        patch.object(entry, "_sample_active_window", return_value="other"),
        patch.object(entry, "_sample_gpu", return_value=(0, 0)),
        patch.object(entry, "_sample_processes", return_value=set()),
        patch.object(
            entry,
            "_sample_filesystem",
            return_value=(None, None, None),
        ),
    ):
        t = threading.Thread(target=entry.main, daemon=True)
        t.start()
        time.sleep(0.05)
        entry._handle_sigterm(signal.SIGTERM, None)
        t.join(timeout=2)

    # At least one push — the final flush.
    assert len(pushed) >= 1
