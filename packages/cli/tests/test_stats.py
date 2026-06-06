"""lablink stats — render correctness + empty state."""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_cfg():
    cfg = MagicMock()
    cfg.ssl.provider = "self_signed"
    cfg.deployment_name = "spring-2026"
    cfg.client.software = "sleap"
    cfg.monitoring.subject_window_patterns = []
    return cfg


def _resp(body):
    return BytesIO(json.dumps(body).encode())


def test_stats_renders_funnel_and_summary(mock_cfg, capsys):
    from lablink_cli.commands.stats import run_stats

    payload = {
        "vms": [
            {
                "HostName": "vm-1",
                "SessionMetricsStartedAt": "x",
                "SecondsToFirstSleapLabel": 300,
                "SecondsToFirstSleapTrain": 1080,
                "SecondsToFirstSleapTrack": 3120,
                "SecondsInSubjectSoftware": 4820,
                "MaxLabeledFrames": 480,
                "TrainingEpochsCompleted": 35,
            },
            {
                "HostName": "vm-2",
                "SessionMetricsStartedAt": "x",
                "SecondsToFirstSleapLabel": 540,
                "SecondsToFirstSleapTrain": None,
                "SecondsToFirstSleapTrack": None,
                "SecondsInSubjectSoftware": 820,
                "MaxLabeledFrames": 40,
                "TrainingEpochsCompleted": 0,
            },
        ],
        "count": 2,
    }

    with (
        patch(
            "lablink_cli.commands.stats.get_allocator_url",
            return_value="https://alloc.example",
        ),
        patch(
            "lablink_cli.commands.stats.resolve_admin_credentials",
            return_value=("admin", "pw"),
        ),
        patch(
            "lablink_cli.commands.stats.urlopen",
            return_value=_resp(payload),
        ),
    ):
        run_stats(mock_cfg)

    out = capsys.readouterr().out
    assert "Funnel" in out
    assert "Started" in out
    assert "Trained" in out
    # 1 of 2 reached training → 50%
    assert "50" in out


def test_stats_handles_empty(mock_cfg, capsys):
    from lablink_cli.commands.stats import run_stats

    payload = {"vms": [], "count": 0}
    with (
        patch(
            "lablink_cli.commands.stats.get_allocator_url",
            return_value="https://alloc.example",
        ),
        patch(
            "lablink_cli.commands.stats.resolve_admin_credentials",
            return_value=("admin", "pw"),
        ),
        patch(
            "lablink_cli.commands.stats.urlopen",
            return_value=_resp(payload),
        ),
    ):
        run_stats(mock_cfg)

    out = capsys.readouterr().out
    assert "No session metrics" in out or "0" in out
