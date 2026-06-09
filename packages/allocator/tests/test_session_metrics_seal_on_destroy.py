"""Destroy paths must bulk-seal session-metrics rows."""

from unittest.mock import MagicMock, patch

import pytest


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

    return {"tmp_path": tmp_path, "database": fake_db}


def test_scheduled_destroy_seals_before_destroy():
    """run_scheduled_destroy must call bulk_seal_session_metrics, then destroy_hosts."""
    from lablink_allocator_service.scheduler import run_scheduled_destroy

    fake_db = MagicMock()
    fake_provider = MagicMock()
    call_order: list[str] = []

    def _seal():
        call_order.append("seal")
        return 3

    def _destroy(handles):
        call_order.append("destroy")
        return MagicMock(stdout="ok")

    fake_db.bulk_seal_session_metrics.side_effect = _seal
    fake_provider.destroy_hosts.side_effect = _destroy

    run_scheduled_destroy(["h1", "h2", "h3"], fake_db, fake_provider)

    assert call_order == ["seal", "destroy"]
    fake_provider.destroy_hosts.assert_called_once_with(["h1", "h2", "h3"])


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch(
    "lablink_allocator_service.providers.aws.current_instance_security_group",
    return_value="sg-allocator-test",
)
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_admin_destroy_route_seals_before_destroy(
    mock_run, mock_sg, mock_ids, mock_names,
    destroy_setup, client, admin_headers,
):
    """POST /destroy must seal session-metrics rows before tear-down."""
    fake_db = destroy_setup["database"]
    call_order: list[str] = []

    def _seal():
        call_order.append("seal")
        return 5

    def _run(*args, **kwargs):
        call_order.append("destroy")
        return MagicMock(
            stdout="Destroy complete (mocked)", stderr="", returncode=0
        )

    fake_db.bulk_seal_session_metrics.side_effect = _seal
    mock_run.side_effect = _run

    resp = client.post("/destroy", headers=admin_headers)

    assert resp.status_code == 200, (
        f"Expected 200, got {resp.status_code}: {resp.get_data(as_text=True)[:300]}"
    )
    fake_db.bulk_seal_session_metrics.assert_called_once()
    assert call_order == ["seal", "destroy"], (
        f"Expected seal before destroy, got {call_order}"
    )


@patch("lablink_allocator_service.providers.aws.get_instance_names", return_value=[])
@patch("lablink_allocator_service.providers.aws.get_instance_ids", return_value=[])
@patch(
    "lablink_allocator_service.providers.aws.current_instance_security_group",
    return_value="sg-allocator-test",
)
@patch("lablink_allocator_service.providers.aws.subprocess.run")
def test_admin_destroy_route_continues_when_seal_fails(
    mock_run, mock_sg, mock_ids, mock_names,
    destroy_setup, client, admin_headers,
):
    """If bulk_seal fails, /destroy logs a warning and continues to destroy."""
    mock_run.return_value = MagicMock(
        stdout="Destroy complete (mocked)", stderr="", returncode=0
    )
    fake_db = destroy_setup["database"]
    fake_db.bulk_seal_session_metrics.side_effect = RuntimeError("db blew up")

    resp = client.post("/destroy", headers=admin_headers)

    assert resp.status_code == 200
    fake_db.bulk_seal_session_metrics.assert_called_once()
    # Destroy still ran despite the seal failure.
    assert mock_run.called
