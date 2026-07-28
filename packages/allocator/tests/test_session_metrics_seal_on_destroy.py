"""Destroy paths must bulk-seal session-metrics rows."""

from unittest.mock import MagicMock, patch

import pytest


class _FakeCompletedPopen:
    """Minimal stand-in for subprocess.Popen matching _run_streamed's
    expected surface — see providers/test_run_streamed.py for the
    canonical version."""

    def __init__(self, stdout_text="", stderr_text="", returncode=0):
        import io
        self.stdout = io.StringIO(stdout_text)
        self.stderr = io.StringIO(stderr_text)
        self._returncode = returncode

    def wait(self):
        return self._returncode


@pytest.fixture
def destroy_setup(app, monkeypatch, tmp_path):
    """Wire fakes for the /destroy route so we can observe its calls.

    Mirrors test_destroy_route_baseline.destroy_setup: writes a dummy
    runtime tfvars file so the route does not 404 early, installs a fresh
    AWSProvider pointed at tmp_path, and replaces main.database with a
    MagicMock.
    """
    from lablink_allocator_service import main
    from lablink_allocator_service.providers.aws import AWSProvider

    monkeypatch.setattr(main, "TERRAFORM_DIR", tmp_path)
    (tmp_path / "terraform.runtime.tfvars").write_text("# stub\n")

    provider = AWSProvider(region="us-west-2", terraform_dir=str(tmp_path))
    monkeypatch.setitem(main.app.config, "LABLINK_PROVIDER", provider)

    fake_db = MagicMock()
    monkeypatch.setattr(main, "database", fake_db, raising=False)

    fake_metrics_db = MagicMock()
    monkeypatch.setattr(main, "metrics_db", fake_metrics_db, raising=False)

    return {"tmp_path": tmp_path, "database": fake_db, "metrics_db": fake_metrics_db}


def test_scheduled_destroy_seals_before_destroy():
    """run_scheduled_destroy must call bulk_seal_session_metrics, then destroy_hosts."""
    from lablink_allocator_service.scheduler import run_scheduled_destroy

    fake_metrics_db = MagicMock()
    fake_provider = MagicMock()
    call_order: list[str] = []

    def _seal():
        call_order.append("seal")
        return 3

    def _destroy(handles):
        call_order.append("destroy")
        return MagicMock(stdout="ok")

    fake_metrics_db.bulk_seal_session_metrics.side_effect = _seal
    fake_provider.destroy_hosts.side_effect = _destroy

    run_scheduled_destroy(["h1", "h2", "h3"], fake_metrics_db, fake_provider)

    assert call_order == ["seal", "destroy"]
    fake_provider.destroy_hosts.assert_called_once_with(["h1", "h2", "h3"])


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch(
    "lablink_allocator_service.providers.aws.current_instance_security_group",
    return_value="sg-allocator-test",
)
@patch("lablink_allocator_service.providers.aws.subprocess.Popen")
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_admin_destroy_route_seals_before_destroy(
    mock_run, mock_popen, mock_sg, mock_ids, mock_names,
    destroy_setup, client, admin_headers,
):
    """POST /destroy's closure must seal session-metrics rows before
    tear-down.

    Since the async rewrite, the route itself only submits a job; the
    seal-then-destroy ordering is enforced inside the closure that runs
    on OperationsWorker's background thread, so we capture and invoke
    that closure directly.
    """
    fake_metrics_db = destroy_setup["metrics_db"]
    call_order: list[str] = []

    def _seal():
        call_order.append("seal")
        return 5

    def _run(cmd, **kwargs):
        # Record "destroy" once, on the first subprocess.run call
        # (`terraform plan -destroy ...`) — the start of the destroy
        # sequence — so call_order still reflects a single seal-then-destroy
        # ordering rather than one entry per plan/show call.
        if not call_order or call_order[-1] != "destroy":
            call_order.append("destroy")
        result = MagicMock()
        result.stdout = '{"resource_changes": []}' if "show" in cmd else "OK"
        result.stderr = ""
        result.returncode = 0
        return result

    fake_metrics_db.bulk_seal_session_metrics.side_effect = _seal
    mock_run.side_effect = _run
    mock_popen.return_value = _FakeCompletedPopen(
        stdout_text="Destroy complete (mocked)\n", returncode=0,
    )

    with patch("lablink_allocator_service.main.operations_worker") as mock_worker:
        mock_worker.submit.return_value = 1
        resp = client.post("/destroy", headers=admin_headers)

        assert resp.status_code == 302, (
            f"Expected redirect, got {resp.status_code}: "
            f"{resp.get_data(as_text=True)[:300]}"
        )

        fn = mock_worker.submit.call_args.kwargs["fn"]
        fn()

    fake_metrics_db.bulk_seal_session_metrics.assert_called_once()
    assert call_order == ["seal", "destroy"], (
        f"Expected seal before destroy, got {call_order}"
    )


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch(
    "lablink_allocator_service.providers.aws.current_instance_security_group",
    return_value="sg-allocator-test",
)
@patch("lablink_allocator_service.providers.aws.subprocess.Popen")
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_admin_destroy_route_continues_when_seal_fails(
    mock_run, mock_popen, mock_sg, mock_ids, mock_names,
    destroy_setup, client, admin_headers,
):
    """If bulk_seal fails, the closure logs a warning and continues to
    destroy."""

    def _run(cmd, **kwargs):
        result = MagicMock()
        result.stdout = '{"resource_changes": []}' if "show" in cmd else "OK"
        result.stderr = ""
        result.returncode = 0
        return result

    mock_run.side_effect = _run
    mock_popen.return_value = _FakeCompletedPopen(
        stdout_text="Destroy complete (mocked)\n", returncode=0,
    )
    fake_metrics_db = destroy_setup["metrics_db"]
    fake_metrics_db.bulk_seal_session_metrics.side_effect = RuntimeError("db blew up")

    with patch("lablink_allocator_service.main.operations_worker") as mock_worker:
        mock_worker.submit.return_value = 1
        resp = client.post("/destroy", headers=admin_headers)

        assert resp.status_code == 302

        fn = mock_worker.submit.call_args.kwargs["fn"]
        fn()

    fake_metrics_db.bulk_seal_session_metrics.assert_called_once()
    # Destroy still ran despite the seal failure.
    assert mock_run.called
    assert mock_popen.called
