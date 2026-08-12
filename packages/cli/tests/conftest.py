"""Shared fixtures for CLI tests."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

import lablink_cli.docker


@pytest.fixture(autouse=True)
def _no_real_docker(request, monkeypatch):
    """Keep unit tests off the developer's docker daemon.

    Two layers, because they catch different mistakes:

    1. The adapter default becomes a :class:`NullDocker`, so CLI code that
       resolves ``default_docker()`` gets inert answers instead of the real
       daemon.
    2. A raw ``subprocess.run(["docker", ...])`` anywhere raises. Every
       docker invocation is supposed to go through the adapter now, so a
       direct spawn means a call site was missed — and a missed call site is
       exactly what once turned a live deployment's Funnel off during a green
       test run. Failing loudly beats faking a reply.

    Tests marked ``integration`` opt out of both; they may legitimately want
    a real daemon.

    This only keeps tests off the docker *daemon*, not off the host in
    general: `register._start_log_shipper` spawns
    `python -m lablink_cli.log_shipper` via a bare ``subprocess.Popen``
    whose ``argv[0]`` is ``sys.executable``, not ``"docker"`` — this guard
    does not (and should not) catch that. A test exercising that path that
    forgets to mock `_start_log_shipper` spawns a real detached process.
    """
    if request.node.get_closest_marker("integration"):
        return

    monkeypatch.setattr(
        lablink_cli.docker, "_default", lablink_cli.docker.NullDocker()
    )

    real_run = subprocess.run

    def guard(cmd, *args, **kwargs):
        argv = cmd if isinstance(cmd, (list, tuple)) else [cmd]
        if argv and argv[0] == "docker":
            raise AssertionError(
                "a test spawned `docker` directly: "
                f"{' '.join(str(a) for a in argv)}\n"
                "Every docker call must go through lablink_cli.docker. "
                "Inject a fake adapter with `docker=` instead."
            )
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guard)


@pytest.fixture(autouse=True)
def no_real_deployment_cache(tmp_path_factory, monkeypatch):
    """Keep test deploys out of the developer's real metrics cache.

    ``DeploymentMetrics`` records land in ``~/.lablink/deployments/`` via a
    module-level constant, so any test reaching a deploy path writes there for
    real. Observed: teaching the compose path to record metrics immediately
    left 25 ``testlab-*.json`` files in the developer's own cache, which then
    show up in their `lablink export-metrics` output as if they were real
    deployments.

    Redirected per-test rather than per-file: the three AWS metrics tests
    already patched this constant by hand, and every other deploy test
    silently did not. Tests that want to seed a cache still monkeypatch the
    same attribute themselves, which simply wins over this default.
    """
    from lablink_cli import deployment_metrics

    monkeypatch.setattr(
        deployment_metrics,
        "DEPLOYMENTS_DIR",
        tmp_path_factory.mktemp("deployments"),
    )


@pytest.fixture()
def mock_cfg():
    """Minimal Config-like object for testing."""
    cfg = MagicMock()
    cfg.deployment_name = "mylab"
    cfg.environment = "dev"
    # Real Config defaults to "aws" (structured_config.Config.provider). Left
    # as a MagicMock it is truthy but never equals any provider string, so
    # provider-dependent code takes neither branch cleanly — and it is not
    # JSON-serializable, which breaks anything persisting it.
    cfg.provider = "aws"
    cfg.app.region = "us-east-1"
    cfg.app.admin_user = "admin"
    cfg.app.admin_password = "secret"
    cfg.machine.software = "sleap"
    cfg.machine.machine_type = "g4dn.xlarge"
    cfg.dns.enabled = False
    cfg.dns.domain = ""
    cfg.dns.terraform_managed = False
    cfg.dns.zone_id = ""
    cfg.ssl.provider = "none"
    cfg.ssl.email = ""
    cfg.ssl.certificate_arn = ""
    cfg.startup_script.enabled = False
    cfg.startup_script.path = ""
    cfg.bucket_name = "lablink-tf-state-123456789012"
    return cfg
