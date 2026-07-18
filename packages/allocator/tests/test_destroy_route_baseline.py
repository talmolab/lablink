"""Regression baseline for /destroy.

Since the async rewrite (PR 2 of the async-terraform-worker roadmap), the
route no longer runs terraform synchronously — it submits a job to
OperationsWorker and returns immediately. These tests assert:
- current_instance_security_group + NotOnEC2Error catch (in provider)
- terraform destroy -auto-approve -var-file=terraform.runtime.tfvars
  [-var=allocator_sg_id=<sg>] — via the captured closure, not the route directly
- ANSI-strip of output (in provider, DestroyResult.stdout is already clean)
- database.clear_database() after success, inside the closure

All AWS-specific calls (current_instance_security_group, subprocess.run for
terraform destroy) execute inside AWSProvider.destroy_hosts — patch them in
the providers.aws namespace, not the main namespace. list_hosts() calls
get_instance_ids / get_instance_names (terraform output), which must also
be patched to avoid real terraform invocations.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def destroy_setup(app, monkeypatch, tmp_path):
    """Standard monkeypatches for /destroy baseline tests. See PR 1's
    version of this fixture for the rationale of each monkeypatch."""
    from lablink_allocator_service import main
    from lablink_allocator_service.providers.aws import AWSProvider

    monkeypatch.setattr(main, "TERRAFORM_DIR", tmp_path)
    (tmp_path / "terraform.runtime.tfvars").write_text("# baseline-test stub\n")

    provider = AWSProvider(region="us-west-2", terraform_dir=str(tmp_path))
    monkeypatch.setitem(main.app.config, "LABLINK_PROVIDER", provider)

    fake_db = MagicMock()
    fake_db.clear_database = MagicMock()
    fake_db.bulk_seal_session_metrics = MagicMock(return_value=0)
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    return {"tmp_path": tmp_path, "database": fake_db}


def _capture_closure(client, admin_headers, mock_worker):
    """POST /destroy and return the `fn` closure captured from the mocked
    operations_worker.submit call, so the test can invoke it directly."""
    r = client.post("/destroy", headers=admin_headers)
    assert r.status_code == 302, (
        f"Expected redirect, got {r.status_code}: {r.get_data(as_text=True)[:300]}"
    )
    mock_worker.submit.assert_called_once()
    return mock_worker.submit.call_args.kwargs["fn"]


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.current_instance_security_group",
       return_value="sg-allocator-test")
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_destroy_submits_job_and_returns_202(
    mock_run, mock_sg, mock_ids, mock_names,
    destroy_setup, client, admin_headers,
):
    """`main.operations_worker` is patched here (like every other test below)
    because the module-level global is `None` until the real allocator's
    `main()` initializes it at process startup; tests never call `main()`,
    so the route would otherwise hit `AttributeError` on `None.submit`.
    """
    mock_run.return_value = MagicMock(
        stdout="Destroy complete (mocked)", stderr="", returncode=0
    )

    with patch("lablink_allocator_service.main.operations_worker") as mock_worker:
        mock_worker.submit.return_value = 42
        r = client.post(
            "/destroy",
            headers={**admin_headers, "Accept": "application/json"},
        )

    assert r.status_code == 202, (
        f"Expected 202, got {r.status_code}: {r.get_data(as_text=True)[:500]}"
    )
    body = r.get_json()
    assert body["status"] == "queued"
    assert isinstance(body["job_id"], int)


def test_destroy_redirects_browser_client_with_job_id(client, admin_headers):
    with patch("lablink_allocator_service.main.operations_worker") as mock_worker:
        mock_worker.submit.return_value = 9
        r = client.post("/destroy", headers=admin_headers, follow_redirects=False)

    assert r.status_code == 302
    assert r.headers["Location"] == "/admin/instances?job=9"


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.current_instance_security_group",
       return_value="sg-allocator-test")
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_destroy_closure_runs_terraform_destroy_and_clears_db(
    mock_run, mock_sg, mock_ids, mock_names,
    destroy_setup, client, admin_headers,
):
    """Capture the closure and invoke it directly — this is what actually
    runs on the background thread."""
    mock_run.return_value = MagicMock(
        stdout="Destroy complete (mocked)", stderr="", returncode=0
    )

    with patch("lablink_allocator_service.main.operations_worker") as mock_worker:
        mock_worker.submit.return_value = 1
        fn = _capture_closure(client, admin_headers, mock_worker)
        output = fn()

    assert "Destroy complete" in output

    calls = mock_run.call_args_list
    cmds = [
        list(c.args[0]) for c in calls
        if c.args and isinstance(c.args[0], (list, tuple))
    ]
    destroy_cmds = [c for c in cmds if c and c[0] == "terraform" and "destroy" in c]
    assert destroy_cmds, f"terraform destroy not called; cmds: {cmds}"
    cmd = destroy_cmds[0]
    assert "-auto-approve" in cmd
    assert "-var-file=terraform.runtime.tfvars" in cmd
    assert any("allocator_sg_id" in arg for arg in cmd)

    destroy_setup["database"].clear_database.assert_called_once()


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.current_instance_security_group",
       return_value="sg-allocator-test")
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_destroy_closure_strips_ansi_from_output(
    mock_run, mock_sg, mock_ids, mock_names,
    destroy_setup, client, admin_headers,
):
    mock_run.return_value = MagicMock(
        stdout="\x1b[32mresources destroyed\x1b[0m", stderr="", returncode=0
    )

    with patch("lablink_allocator_service.main.operations_worker") as mock_worker:
        mock_worker.submit.return_value = 1
        fn = _capture_closure(client, admin_headers, mock_worker)
        output = fn()

    assert "resources destroyed" in output
    assert "\x1b[" not in output


def test_destroy_closure_fails_when_no_runtime_tfvars(
    monkeypatch, tmp_path, client, admin_headers,
):
    """No terraform.runtime.tfvars -> the closure raises RuntimeError (marks
    the operation failed) instead of the route returning 404 synchronously."""
    from lablink_allocator_service import main
    from lablink_allocator_service.providers.aws import AWSProvider

    monkeypatch.setattr(main, "TERRAFORM_DIR", tmp_path)
    provider = AWSProvider(region="us-west-2", terraform_dir=str(tmp_path))
    monkeypatch.setitem(main.app.config, "LABLINK_PROVIDER", provider)
    fake_db = MagicMock()
    fake_db.bulk_seal_session_metrics = MagicMock(return_value=0)
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    with patch("lablink_allocator_service.providers.aws.get_instance_ids",
               return_value=[]), \
         patch("lablink_allocator_service.providers.aws.get_instance_names",
               return_value=[]), \
         patch("lablink_allocator_service.main.operations_worker") as mock_worker:
        mock_worker.submit.return_value = 1
        fn = _capture_closure(client, admin_headers, mock_worker)

        with pytest.raises(RuntimeError, match="tfvars does not exist"):
            fn()


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch("lablink_allocator_service.providers.aws.current_instance_security_group",
       return_value="sg-allocator-test")
def test_destroy_closure_wraps_terraform_failure(
    mock_sg, mock_ids, mock_names, destroy_setup, client, admin_headers,
):
    import subprocess

    with patch(
        "lablink_allocator_service.providers.aws.subprocess.run",
        side_effect=subprocess.CalledProcessError(
            1, ["terraform", "destroy"], stderr="\x1b[31mError: boom\x1b[0m",
        ),
    ), patch("lablink_allocator_service.main.operations_worker") as mock_worker:
        mock_worker.submit.return_value = 1
        fn = _capture_closure(client, admin_headers, mock_worker)

        with pytest.raises(RuntimeError, match="Error: boom"):
            fn()


def test_destroy_returns_409_when_operation_in_progress(client, admin_headers):
    from lablink_allocator_service.operations_db import OperationInProgress

    with patch("lablink_allocator_service.main.operations_worker") as mock_worker:
        mock_worker.submit.side_effect = OperationInProgress(job_id=4)
        r = client.post(
            "/destroy",
            headers={**admin_headers, "Accept": "application/json"},
        )

    assert r.status_code == 409
    body = r.get_json()
    assert body["job_id"] == 4
    assert "already in progress" in body["error"]


def test_destroy_returns_405_when_provider_cannot_destroy(
    monkeypatch, client, admin_headers,
):
    """After Task 8, the route returns 405 when the provider can't destroy."""
    from lablink_allocator_service import main

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
