"""Structural test for start.sh's tutorial-repo clone guard.

Allocators predating the tfvars fix (providers/aws.py) f-string a Python
None into the literal string "None", shipping TUTORIAL_REPO_TO_CLONE="None"
to every VM -- non-empty, so the old `-n`-only gate ran `git clone None`
and logged its failure on every boot. The guard makes new client images
immune regardless of the allocator's version.

Same text-assertion approach as test_start_sh_status.py: start.sh is not
sourceable as a whole.
"""

from pathlib import Path

START_SH = Path(__file__).resolve().parents[1] / "start.sh"


def test_clone_skips_the_literal_string_none():
    text = START_SH.read_text()
    gate = next(
        ln for ln in text.splitlines() if "TUTORIAL_REPO_TO_CLONE" in ln and "if " in ln
    )
    assert '[ -n "$TUTORIAL_REPO_TO_CLONE" ]' in gate
    assert '[ "$TUTORIAL_REPO_TO_CLONE" != "None" ]' in gate
