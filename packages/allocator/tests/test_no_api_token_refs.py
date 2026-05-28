"""Guard test: after PR D4, no source file under packages/ should reference
API_TOKEN. The CHANGELOG entry announcing the removal is excluded.
"""

import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGES = REPO_ROOT / "packages"


def test_no_api_token_references_in_source():
    """grep -rn API_TOKEN under packages/ in source files — must return zero hits."""
    if not PACKAGES.is_dir():
        # Test ships inside the allocator docker image / installed wheel where the
        # monorepo layout doesn't exist. The guard's purpose is to catch a
        # regression at PR-review time on a full checkout; skip elsewhere.
        pytest.skip(f"packages/ not found at {PACKAGES} (not running from repo tree)")
    result = subprocess.run(
        [
            "grep",
            "-rn",
            "--include=*.py",
            "--include=*.sh",
            "--include=*.tf",
            "API_TOKEN",
            str(PACKAGES),
        ],
        capture_output=True,
        text=True,
    )
    # grep exit 1 = no matches (success)
    # grep exit 0 = matches found (failure)
    if result.returncode == 0:
        # Filter out lines from test files (they're allowed to use the string)
        lines = [
            line
            for line in result.stdout.splitlines()
            if "/tests/" not in line
        ]
        if lines:
            raise AssertionError(
                "Unexpected API_TOKEN references in source after PR D4:\n"
                + "\n".join(lines)
            )
    elif result.returncode != 1:
        # grep error (other than no-match) — report it
        raise AssertionError(f"grep failed: {result.stderr}")


def test_no_api_token_references_in_changelog_except_retirement_context():
    """The CLI CHANGELOG may mention API_TOKEN only in retired/removed context."""
    changelog = REPO_ROOT / "packages" / "cli" / "CHANGELOG.md"
    if not changelog.exists():
        pytest.skip(f"CHANGELOG not found at {changelog} (not running from repo tree)")
    content = changelog.read_text()
    suspicious_lines = [
        line
        for line in content.splitlines()
        if "API_TOKEN" in line
        and not any(
            phrase in line.lower()
            for phrase in ("retired", "removed", "drop", "no longer")
        )
    ]
    assert not suspicious_lines, (
        f"Unexpected API_TOKEN CHANGELOG mentions (outside retirement context): "
        f"{suspicious_lines}"
    )
