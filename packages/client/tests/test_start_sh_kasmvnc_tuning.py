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
