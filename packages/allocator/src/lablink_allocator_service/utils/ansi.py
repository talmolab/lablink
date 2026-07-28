"""ANSI escape-sequence stripping for terraform output and client VM logs.

Lives here rather than in main.py because three call sites across two
blueprints need it (provisioning: terraform stdout/stderr; vm_telemetry:
client log ingestion) and it holds no state.
"""

import re

# CSI sequences plus the two-character escapes terraform emits for color.
ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(text: str) -> str:
    """Return *text* with ANSI escape sequences removed."""
    return ANSI_ESCAPE.sub("", text)
