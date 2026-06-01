"""Pre-refactor regression baseline for /destroy.

After Tasks 7-8, /destroy calls provider.destroy_hosts(...) which performs:
- FileNotFoundError if no terraform.runtime.tfvars exists (→ 404)
- current_instance_security_group + NotOnEC2Error catch (in provider)
- terraform destroy -auto-approve -var-file=terraform.runtime.tfvars
  [-var=allocator_sg_id=<sg>]
- ANSI-strip of output (in provider, DestroyResult.stdout is already clean)
- database.clear_database() after success (still in route)

Post-Task-8 note: all AWS-specific calls (current_instance_security_group,
subprocess.run for terraform destroy) now execute inside AWSProvider.destroy_hosts —
patch them in the providers.aws namespace, not the main namespace.
list_hosts() calls get_instance_ids / get_instance_names (terraform output),
which must also be patched to avoid real terraform invocations.
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

    Post-Task-8: also replaces LABLINK_PROVIDER in app.config with a fresh
    AWSProvider pointing at tmp_path, so destroy_hosts checks for the
    runtime tfvars in tmp_path and calls terraform in the tmp directory.

    Writes terraform.runtime.tfvars to tmp_path so the route does not
    early-return 404 (that path is tested separately in
    test_destroy_returns_404_when_no_runtime_tfvars).
    """
    from lablink_allocator_service import main
    from lablink_allocator_service.providers.aws import AWSProvider

    monkeypatch.setattr(main, "TERRAFORM_DIR", tmp_path)
    (tmp_path / "terraform.runtime.tfvars").write_text("# baseline-test stub\n")

    # Wire a fresh AWSProvider pointing at tmp_path so destroy_hosts
    # checks for tfvars and runs terraform relative to tmp_path.
    provider = AWSProvider(region="us-west-2", terraform_dir=str(tmp_path))
    monkeypatch.setitem(main.app.config, "LABLINK_PROVIDER", provider)

    fake_db = MagicMock()
    fake_db.clear_database = MagicMock()
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    return {"tmp_path": tmp_path, "database": fake_db}


# ---------------------------------------------------------------------------
# Baseline tests
# ---------------------------------------------------------------------------

@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.current_instance_security_group",
       return_value="sg-allocator-test")
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_destroy_runs_terraform_destroy(
    mock_run, mock_sg, mock_ids, mock_names,
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


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.current_instance_security_group",
       return_value="sg-allocator-test")
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_destroy_clears_database_on_success(
    mock_run, mock_sg, mock_ids, mock_names,
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
    from lablink_allocator_service.providers.aws import AWSProvider

    monkeypatch.setattr(main, "TERRAFORM_DIR", tmp_path)
    # Intentionally do NOT create tfvars so the provider raises FileNotFoundError
    # which the route maps to 404.
    provider = AWSProvider(region="us-west-2", terraform_dir=str(tmp_path))
    monkeypatch.setitem(main.app.config, "LABLINK_PROVIDER", provider)

    with patch("lablink_allocator_service.providers.aws.get_instance_ids",
               return_value=[]), \
         patch("lablink_allocator_service.providers.aws.get_instance_names",
               return_value=[]):
        r = client.post(
            "/destroy",
            headers={**admin_headers, "Accept": "application/json"},
        )
    assert r.status_code == 404, (
        f"Expected 404 when no tfvars, got {r.status_code}: "
        f"{r.get_data(as_text=True)[:300]}"
    )


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.current_instance_security_group",
       return_value="sg-allocator-test")
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_destroy_strips_ansi_from_output(
    mock_run, mock_sg, mock_ids, mock_names,
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


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.current_instance_security_group",
       return_value="sg-allocator-test")
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_destroy_json_response_on_success(
    mock_run, mock_sg, mock_ids, mock_names,
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


def test_destroy_returns_405_when_provider_cannot_destroy(
    monkeypatch, client, admin_headers,
):
    """After Task 8, the route returns 405 when the provider can't destroy."""
    from lablink_allocator_service import main

    # Force can_destroy_hosts=False via a fake provider in app.config
    fake_provider = type("FakeProvider", (), {
        "can_provision_hosts": False,
        "can_destroy_hosts": False,
        "can_recover_hosts": False,
        "name": "manual",
    })()
    main.app.config["LABLINK_PROVIDER"] = fake_provider

    r = client.post(
        "/destroy",
        headers={**admin_headers, "Accept": "application/json"},
    )
    assert r.status_code == 405, \
        f"expected 405 when provider can't destroy; got {r.status_code}"
