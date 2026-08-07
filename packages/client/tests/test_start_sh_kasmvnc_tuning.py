"""Structural tests for start.sh's XFCE compositing override and KasmVNC
encoder tuning.

start.sh isn't sourceable as a whole -- it `exec`s stdout through a tagger
and launches long-running services -- so these extract just the two
config-generator blocks, run them in a bash subprocess against a temporary
HOME, and parse the files they produce.

Parsing rather than grepping is the point for the YAML. `encoding:` must be
a TOP-LEVEL key; appended one indent level too deep it nests under
`logging:` and KasmVNC ignores it *without an error*. A string assertion
passes on that broken config and the deployment silently keeps the stock
defaults, which is exactly the bug this work exists to fix.
"""

import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

START_SH = Path(__file__).resolve().parents[1] / "start.sh"

# (marker that identifies the block's first line, exact closing line)
BLOCKS = [
    ("mkdir -p /home/client/.config/xfce4/xfconf", "XFWM"),
    ("cat > /home/client/.vnc/kasmvnc.yaml", "KASMYAML"),
]


def _extract(script_text: str, start_contains: str, closer: str) -> str:
    """Lines from the first line containing `start_contains` through the
    next line exactly equal to `closer`, inclusive. The search for the
    closer starts one line down because a heredoc's opening line also
    contains its delimiter."""
    lines = script_text.splitlines()
    start = next(i for i, ln in enumerate(lines) if start_contains in ln)
    end = next(
        i for i in range(start + 1, len(lines)) if lines[i] == closer
    )
    return "\n".join(lines[start : end + 1])


@pytest.fixture(scope="module")
def script_text() -> str:
    return START_SH.read_text()


@pytest.fixture(scope="module")
def generated(tmp_path_factory, script_text) -> Path:
    """Run both generator blocks with /home/client redirected at a tmpdir,
    and return that tmpdir."""
    home = tmp_path_factory.mktemp("home")
    (home / ".vnc").mkdir()
    for marker, closer in BLOCKS:
        snippet = _extract(script_text, marker, closer).replace(
            "/home/client", str(home)
        )
        result = subprocess.run(
            ["bash", "-c", snippet],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
    return home


@pytest.fixture(scope="module")
def xfwm4_xml(generated) -> ET.Element:
    path = (
        generated
        / ".config/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml"
    )
    return ET.parse(path).getroot()


def test_xfwm4_channel_disables_compositing(xfwm4_xml):
    """The compositor is what turns a window drag into one full-screen
    damage rect, so Xvnc re-encodes the whole framebuffer per frame."""
    assert xfwm4_xml.get("name") == "xfwm4"
    general = xfwm4_xml.find("./property[@name='general']")
    assert general is not None, "no <property name='general'> in channel"
    prop = general.find("./property[@name='use_compositing']")
    assert prop is not None, "use_compositing not set under general"
    assert prop.get("type") == "bool"
    assert prop.get("value") == "false"


def test_xfwm4_config_written_before_the_session_launches(script_text):
    """xfconf reads the XML store once, at session start. Written after
    xfce4-session is up it would be ignored until the next boot -- and
    there is no next boot inside one participant session."""
    lines = script_text.splitlines()
    xml_at = next(i for i, ln in enumerate(lines) if "xfwm4.xml" in ln)
    launch_at = next(
        i
        for i, ln in enumerate(lines)
        if "/home/client/.vnc/xstartup" in ln and "DISPLAY=:1" in ln
    )
    assert xml_at < launch_at


@pytest.fixture(scope="module")
def kasmvnc_yaml(generated) -> dict:
    return yaml.safe_load((generated / ".vnc/kasmvnc.yaml").read_text())


def test_encoding_is_a_top_level_key(kasmvnc_yaml):
    """One indent level too deep and `encoding:` nests under `logging:`,
    where KasmVNC ignores it silently -- no warning, no error, just the
    stock defaults. This is the assertion a string grep cannot make."""
    assert "encoding" in kasmvnc_yaml
    assert "encoding" not in kasmvnc_yaml.get("logging", {})
    assert "encoding" not in kasmvnc_yaml.get("network", {})


def test_dynamic_quality_floor_is_widened(kasmvnc_yaml):
    """Stock band is 7-8, pinned near maximum, so the encoder holds
    near-lossless through a full-screen redraw and falls behind rather
    than degrading. KasmVNC varies quality within this band by how fast
    the screen is CHANGING -- not by network feedback -- so lowering the
    floor is what buys smooth motion."""
    rect = kasmvnc_yaml["encoding"]["rect_encoding_mode"]
    assert rect["min_quality"] == 4
    assert rect["max_quality"] == 8


def test_video_mode_engages_sooner(kasmvnc_yaml):
    """Stock 5s: a drag or scroll spends five seconds in per-rect
    JPEG/WebP before video mode engages."""
    video = kasmvnc_yaml["encoding"]["video_encoding_mode"]
    assert video["enter_video_encoding_mode"]["time_threshold"] == 2


def test_vertical_scroll_detection_is_enabled(kasmvnc_yaml):
    """Ships off. Sends a cheap region shift instead of re-encoding the
    scrolled region."""
    scrolling = kasmvnc_yaml["encoding"]["scrolling"]
    assert scrolling["detect_vertical_scrolling"] is True


def test_heredoc_conversion_preserved_the_existing_settings(kasmvnc_yaml):
    """The echo-line block became a heredoc in the same edit that added
    `encoding:`. These four are what the old block existed for: without
    them Xvnc will not start (unreadable snakeoil cert) or nginx cannot
    reach it (require_ssl on a plain-ws upstream)."""
    assert kasmvnc_yaml["network"]["protocol"] == "http"
    assert kasmvnc_yaml["network"]["ssl"]["require_ssl"] is False
    assert kasmvnc_yaml["network"]["ssl"]["pem_certificate"].endswith(
        "/.vnc/kasmvnc.pem"
    )
    assert kasmvnc_yaml["logging"]["level"] == 100
