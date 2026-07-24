"""Guard test: after fixing talmolab/lablink#377, dashboard.html and
delete-dashboard.html are retired (POST /api/launch and POST /destroy
always redirect instead of rendering a template inline). Nothing under
packages/ should reference them.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGES = REPO_ROOT / "packages"


@pytest.mark.parametrize("template_name", ["dashboard.html", "delete-dashboard.html"])
def test_template_file_is_gone(template_name):
    templates_dir = (
        Path(__file__).resolve().parents[1]
        / "src" / "lablink_allocator_service" / "templates"
    )
    assert not (templates_dir / template_name).exists()


@pytest.mark.parametrize("template_name", ["dashboard.html", "delete-dashboard.html"])
def test_no_source_references_retired_template(template_name):
    if not PACKAGES.is_dir():
        pytest.skip(f"packages/ not found at {PACKAGES} (not running from repo tree)")
    result = subprocess.run(
        [
            "grep", "-rn", "-I", "--exclude-dir=__pycache__",
            template_name, str(PACKAGES),
        ],
        capture_output=True, text=True,
    )
    hits = [
        line for line in result.stdout.splitlines()
        if "test_no_dashboard_template_refs.py" not in line
    ]
    assert not hits, f"Found lingering references to {template_name}: {hits}"
