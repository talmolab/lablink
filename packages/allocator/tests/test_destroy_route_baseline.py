"""Pre-refactor regression baseline for /destroy.

Today's /destroy route inlines:
- has_runtime_tfvars (returns 404 if no tfvars on disk)
- current_instance_security_group + NotOnEC2Error catch
- terraform destroy -auto-approve -var-file=terraform.runtime.tfvars
  [-var=allocator_sg_id=<sg>]
- database.clear_database() after success
- ANSI-strip + delete-dashboard.html render (or JSON)

After Tasks 7-8, /destroy calls provider.destroy_hosts(...) which performs
the same effects. These tests assert behavior, not code shape, so they
survive both states.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared setup
# ---------------------------------------------------------------------------

@pytest.fixture
def destroy_setup(app, monkeypatch, tmp_path):
    """Standard monkeypatches for /destroy baseline tests.

    Depends on `app` so these monkeypatches run after the `app` fixture
    sets up the Flask test context — preventing the `app` fixture's direct
    `main.database = MagicMock()` assignment from overwriting our fake_db.

    Writes terraform.runtime.tfvars to tmp_path so the route does not
    early-return 404 (that path is tested separately in
    test_destroy_returns_404_when_no_runtime_tfvars).
    """
    from lablink_allocator_service import main

    monkeypatch.setattr(main, "TERRAFORM_DIR", tmp_path)
    (tmp_path / "terraform.runtime.tfvars").write_text("# baseline-test stub\n")

    fake_db = MagicMock()
    fake_db.clear_database = MagicMock()
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    return {"tmp_path": tmp_path, "database": fake_db}


# ---------------------------------------------------------------------------
# Baseline tests
# ---------------------------------------------------------------------------

@patch("lablink_allocator_service.main.current_instance_security_group",
       return_value="sg-allocator-test")
@patch("lablink_allocator_service.main.subprocess.run")
def test_destroy_runs_terraform_destroy(
    mock_run, mock_sg,
    destroy_setup, client, admin_headers,
):
    """Baseline: terraform destroy is called with the required flags."""
    mock_run.return_value = MagicMock(
        stdout="Destroy complete (mocked)", stderr="", returncode=0
    )

    r = client.post("/destroy", headers=admin_headers)

    assert r.status_code == 200, (
        f"Expected 200, got {r.status_code}: {r.get_data(as_text=True)[:500]}"
    )

    calls = mock_run.call_args_list
    cmds = [
        list(c.args[0])
        for c in calls
        if c.args and isinstance(c.args[0], (list, tuple))
    ]
    destroy_cmds = [
        c for c in cmds
        if c and c[0] == "terraform" and "destroy" in c
    ]
    assert destroy_cmds, f"terraform destroy not called; cmds: {cmds}"

    cmd = destroy_cmds[0]
    assert "-auto-approve" in cmd, f"-auto-approve missing: {cmd}"
    assert "-var-file=terraform.runtime.tfvars" in cmd, (
        f"-var-file=terraform.runtime.tfvars missing: {cmd}"
    )
    assert any("allocator_sg_id" in arg for arg in cmd), (
        f"allocator_sg_id var missing from destroy cmd: {cmd}"
    )


@patch("lablink_allocator_service.main.current_instance_security_group",
       return_value="sg-allocator-test")
@patch("lablink_allocator_service.main.subprocess.run")
def test_destroy_clears_database_on_success(
    mock_run, mock_sg,
    destroy_setup, client, admin_headers,
):
    """Baseline: database.clear_database() is called after successful destroy."""
    mock_run.return_value = MagicMock(
        stdout="Destroy complete (mocked)", stderr="", returncode=0
    )

    client.post("/destroy", headers=admin_headers)

    destroy_setup["database"].clear_database.assert_called_once()


def test_destroy_returns_404_when_no_runtime_tfvars(
    monkeypatch, tmp_path, client, admin_headers,
):
    """Baseline: /destroy returns 404 when no terraform.runtime.tfvars exists."""
    from lablink_allocator_service import main

    monkeypatch.setattr(main, "TERRAFORM_DIR", tmp_path)
    # Intentionally do NOT create tfvars so the route returns 404.

    r = client.post(
        "/destroy",
        headers={**admin_headers, "Accept": "application/json"},
    )
    assert r.status_code == 404, (
        f"Expected 404 when no tfvars, got {r.status_code}: "
        f"{r.get_data(as_text=True)[:300]}"
    )


@patch("lablink_allocator_service.main.current_instance_security_group",
       return_value="sg-allocator-test")
@patch("lablink_allocator_service.main.subprocess.run")
def test_destroy_strips_ansi_from_output(
    mock_run, mock_sg,
    destroy_setup, client, admin_headers,
):
    """Baseline: ANSI escape codes are stripped from terraform destroy output."""
    mock_run.return_value = MagicMock(
        stdout="\x1b[32mresources destroyed\x1b[0m", stderr="", returncode=0
    )

    r = client.post("/destroy", headers=admin_headers)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "resources destroyed" in body
    assert "\x1b[" not in body, "ANSI escape codes were NOT stripped from response"


@patch("lablink_allocator_service.main.current_instance_security_group",
       return_value="sg-allocator-test")
@patch("lablink_allocator_service.main.subprocess.run")
def test_destroy_json_response_on_success(
    mock_run, mock_sg,
    destroy_setup, client, admin_headers,
):
    """Baseline: JSON-accepting client gets status=success + output on destroy."""
    mock_run.return_value = MagicMock(
        stdout="Destroy complete (mocked)", stderr="", returncode=0
    )

    r = client.post(
        "/destroy",
        headers={**admin_headers, "Accept": "application/json"},
    )
    assert r.status_code == 200
    body = json.loads(r.get_data(as_text=True))
    assert body["status"] == "success"
    assert "Destroy complete" in body["output"]
