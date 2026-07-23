"""lablink stats — rendering against /api/session-metrics/summary."""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_cfg():
    cfg = MagicMock()
    cfg.ssl.provider = "self_signed"
    cfg.deployment_name = "spring-2026"
    return cfg


def _resp(body):
    return BytesIO(json.dumps(body).encode())


_POPULATED = {
    "enabled": True,
    "subject_software_label": "sleap",
    "summary": {
        "total_vms": 2,
        "funnel": {"started": 2, "labeled": 2, "trained": 1, "tracked": 0},
        "pct_reached_training": 50.0,
        "median_seconds_in_subject_software": 2820,
        "median_seconds_to_first_train": 1080,
        "median_labeled_frames": 260,
        "median_epochs_completed": 17,
    },
}


def _patches(payload):
    return (
        patch(
            "lablink_cli.commands.stats.get_allocator_url",
            return_value="https://alloc.example",
        ),
        patch(
            "lablink_cli.commands.stats.resolve_admin_credentials",
            return_value=("admin", "pw"),
        ),
        patch(
            "lablink_cli.api.urlopen",
            return_value=_resp(payload),
        ),
    )


def test_stats_renders_funnel_summary_and_pct_training(mock_cfg, capsys):
    from lablink_cli.commands.stats import run_stats

    p1, p2, p3 = _patches(_POPULATED)
    with p1, p2, p3:
        run_stats(mock_cfg)

    out = capsys.readouterr().out
    assert "Funnel" in out
    for stage in ("Started", "Labeled", "Trained", "Tracked"):
        assert stage in out
    assert "50" in out  # pct_reached_training
    assert "% reached training" in out
    assert "sleap" in out  # subject software label from server, not cfg


def test_stats_handles_zero_vms(mock_cfg, capsys):
    from lablink_cli.commands.stats import run_stats

    zero_payload = {
        "enabled": True,
        "subject_software_label": "sleap",
        "summary": {
            "total_vms": 0,
            "funnel": {"started": 0, "labeled": 0, "trained": 0, "tracked": 0},
            "pct_reached_training": 0.0,
            "median_seconds_in_subject_software": None,
            "median_seconds_to_first_train": None,
            "median_labeled_frames": None,
            "median_epochs_completed": None,
        },
    }
    p1, p2, p3 = _patches(zero_payload)
    with p1, p2, p3:
        run_stats(mock_cfg)

    out = capsys.readouterr().out
    assert "No session metrics" in out


def test_stats_handles_disabled_monitoring(mock_cfg, capsys):
    from lablink_cli.commands.stats import run_stats

    disabled_payload = {
        "enabled": False,
        "subject_software_label": "sleap",
        "summary": None,
    }
    p1, p2, p3 = _patches(disabled_payload)
    with p1, p2, p3:
        run_stats(mock_cfg)

    out = capsys.readouterr().out
    assert "disabled" in out.lower()
    # Should NOT crash trying to render a None summary.


def test_stats_uses_label_from_server_not_local_cfg(mock_cfg, capsys):
    """The label rendered must come from the response, not cfg.monitoring."""
    from lablink_cli.commands.stats import run_stats

    payload = dict(_POPULATED)
    payload["subject_software_label"] = "custom_app"
    # Even if local cfg disagreed, the rendered label should be "custom_app".
    mock_cfg.monitoring.subject_window_patterns = ["something_else"]

    p1, p2, p3 = _patches(payload)
    with p1, p2, p3:
        run_stats(mock_cfg)

    out = capsys.readouterr().out
    assert "custom_app" in out
    assert "something_else" not in out


def test_stats_hits_summary_endpoint_not_export_metrics(mock_cfg):
    """Regression: stats must call /api/session-metrics/summary."""
    from lablink_cli.commands.stats import run_stats

    p1, p2 = (
        patch(
            "lablink_cli.commands.stats.get_allocator_url",
            return_value="https://alloc.example",
        ),
        patch(
            "lablink_cli.commands.stats.resolve_admin_credentials",
            return_value=("admin", "pw"),
        ),
    )
    with p1, p2, patch(
        "lablink_cli.api.urlopen",
        return_value=_resp(_POPULATED),
    ) as mock_urlopen:
        run_stats(mock_cfg)

    called_url = mock_urlopen.call_args[0][0].full_url
    assert called_url.endswith("/api/session-metrics/summary"), called_url
