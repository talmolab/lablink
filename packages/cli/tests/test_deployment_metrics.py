"""Tests for the deployment_metrics helper module (issue #317)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from lablink_cli import deployment_metrics
from lablink_cli.deployment_metrics import (
    DeploymentMetrics,
    cache_path_for,
    load_all_metrics,
    phase_timer,
    write_metrics,
)


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Redirect DEPLOYMENTS_DIR to a tmp dir for isolation."""
    d = tmp_path / "deployments"
    monkeypatch.setattr(deployment_metrics, "DEPLOYMENTS_DIR", d)
    return d


def test_cache_path_is_stable_for_same_inputs(cache_dir):
    dt = datetime(2026, 4, 10, 14, 2, 5, tzinfo=timezone.utc)
    p1 = cache_path_for("prod-lab", dt)
    p2 = cache_path_for("prod-lab", dt)
    assert p1 == p2
    assert p1.parent == cache_dir


def test_cache_path_escapes_colons(cache_dir):
    dt = datetime(2026, 4, 10, 14, 2, 5, tzinfo=timezone.utc)
    p = cache_path_for("prod-lab", dt)
    assert ":" not in p.name


def test_write_metrics_creates_parent_dir(cache_dir):
    metrics = DeploymentMetrics(deployment_name="x")
    target = cache_dir / "deep" / "nested" / "metrics.json"
    write_metrics(target, metrics)
    assert target.exists()


def test_write_metrics_atomic_no_partial_file(cache_dir):
    metrics = DeploymentMetrics(deployment_name="x")
    target = cache_dir / "metrics.json"
    write_metrics(target, metrics)
    assert target.exists()
    assert not target.with_suffix(".json.tmp").exists()


def test_write_and_read_roundtrip(cache_dir):
    dt = datetime(2026, 4, 10, 14, 2, 5, tzinfo=timezone.utc)
    metrics = DeploymentMetrics(
        deployment_name="prod-lab",
        region="us-east-1",
        template_version="v0.2.0",
        ssl_enabled=True,
        allocator_deploy_start_time=dt.isoformat(),
        allocator_terraform_init_duration_seconds=4.8,
        status="success",
    )
    write_metrics(cache_path_for("prod-lab", dt), metrics)

    loaded = load_all_metrics()
    assert len(loaded) == 1
    row = loaded[0]
    assert row["deployment_name"] == "prod-lab"
    assert row["region"] == "us-east-1"
    assert row["allocator_terraform_init_duration_seconds"] == 4.8
    assert row["status"] == "success"


def test_load_all_metrics_empty_dir(cache_dir):
    # Don't even create the dir
    assert load_all_metrics() == []


def test_load_all_metrics_skips_malformed_files(cache_dir):
    cache_dir.mkdir(parents=True)
    good = cache_dir / "good.json"
    good.write_text(json.dumps({"deployment_name": "ok"}))
    bad = cache_dir / "bad.json"
    bad.write_text("{not valid json")

    rows = load_all_metrics()
    assert len(rows) == 1
    assert rows[0]["deployment_name"] == "ok"


def test_phase_timer_records_duration_and_persists(cache_dir, monkeypatch):
    metrics = DeploymentMetrics(deployment_name="x")
    target = cache_dir / "x.json"

    times = iter([100.0, 105.5])
    monkeypatch.setattr(
        deployment_metrics.time, "monotonic", lambda: next(times)
    )

    with phase_timer(
        metrics, "allocator_terraform_init_duration_seconds", target
    ):
        pass

    assert metrics.allocator_terraform_init_duration_seconds == 5.5
    on_disk = json.loads(target.read_text())
    assert on_disk["allocator_terraform_init_duration_seconds"] == 5.5


def test_phase_timer_persists_on_exception(cache_dir, monkeypatch):
    """Failing phase still persists its partial duration."""
    metrics = DeploymentMetrics(deployment_name="x")
    target = cache_dir / "x.json"

    times = iter([100.0, 102.0])
    monkeypatch.setattr(
        deployment_metrics.time, "monotonic", lambda: next(times)
    )

    with pytest.raises(RuntimeError):
        with phase_timer(
            metrics, "allocator_terraform_apply_duration_seconds", target
        ):
            raise RuntimeError("apply failed")

    assert metrics.allocator_terraform_apply_duration_seconds == 2.0
    on_disk = json.loads(target.read_text())
    assert on_disk["allocator_terraform_apply_duration_seconds"] == 2.0
