"""Active-window sampler — bucket assignment and fallback behaviour."""

from unittest.mock import patch

from lablink_client_service.monitoring.samplers import active_window


def test_sample_returns_subject_for_sleap_title_with_sleap_pattern():
    with patch(
        "lablink_client_service.monitoring.samplers.active_window._get_title",
        return_value="SLEAP — labels.v001.slp",
    ):
        assert active_window.sample(subject_patterns=["sleap"]) == "subject"


def test_sample_returns_subject_for_deeplabcut_title_with_deeplabcut_pattern():
    with patch(
        "lablink_client_service.monitoring.samplers.active_window._get_title",
        return_value="DeepLabCut 2.3 — my_project",
    ):
        assert active_window.sample(subject_patterns=["deeplabcut"]) == "subject"


def test_sample_returns_other_when_subject_pattern_does_not_match():
    with patch(
        "lablink_client_service.monitoring.samplers.active_window._get_title",
        return_value="SLEAP — labels.slp",
    ):
        assert active_window.sample(subject_patterns=["deeplabcut"]) == "other"


def test_sample_returns_terminal_for_xterm_title():
    with patch(
        "lablink_client_service.monitoring.samplers.active_window._get_title",
        return_value="xterm",
    ):
        assert active_window.sample(subject_patterns=["sleap"]) == "terminal"


def test_sample_returns_browser_for_firefox_title():
    with patch(
        "lablink_client_service.monitoring.samplers.active_window._get_title",
        return_value="GitHub — Mozilla Firefox",
    ):
        assert active_window.sample(subject_patterns=["sleap"]) == "browser"


def test_sample_returns_other_for_unknown_title():
    with patch(
        "lablink_client_service.monitoring.samplers.active_window._get_title",
        return_value="Calculator",
    ):
        assert active_window.sample(subject_patterns=["sleap"]) == "other"


def test_sample_returns_other_when_xdotool_missing():
    with patch(
        "lablink_client_service.monitoring.samplers.active_window._get_title",
        return_value=None,
    ):
        assert active_window.sample(subject_patterns=["sleap"]) == "other"


def test_sample_with_empty_patterns_never_matches_subject():
    with patch(
        "lablink_client_service.monitoring.samplers.active_window._get_title",
        return_value="SLEAP — labels.slp",
    ):
        assert active_window.sample(subject_patterns=[]) == "other"
