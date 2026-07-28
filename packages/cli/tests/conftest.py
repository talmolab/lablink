"""Shared fixtures for CLI tests."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def no_real_docker(request):
    """Stop tests from driving the developer's real Docker daemon.

    The CLI shells out to `docker` against fixed container names —
    `lablink-allocator-tailscale`, `lablink-client` — from deploy_compose,
    register, log_shipper and the logs viewer. Several of those commands
    mutate state: `_disable_funnel` runs `tailscale funnel --https=443 off`,
    and register can `docker rm -f lablink-client`.

    22 tests reach `run_deploy_compose` without mocking `_disable_funnel`, so
    on a machine running a live LabLink stack a green test run silently turned
    that deployment's Funnel off — the public URL simply stopped working, with
    nothing in the test output to say so. Reproduced directly: Funnel on ->
    `pytest tests/test_deploy_compose.py` (101 passed) -> "No serve config".

    `docker volume inspect` leaked the other way: unmocked, it read the
    developer's real volumes, so whether a test saw an existing
    `<name>_tailscale_state` depended on what happened to be on their machine.

    This guard answers every `docker` invocation with the not-found result a
    machine with no such container or volume would give. That is the honest
    model for a unit-test environment, and it is what the callers already
    handle: `_disable_funnel` is documented best-effort and stays silent on
    failure, `_tailscale_state_volume_exists` reports False. Tests that mean
    to exercise a docker-invoking helper patch `subprocess.run` in their own
    module, which takes precedence over this fixture and is restored after.

    Non-docker subprocess calls pass straight through, and tests marked
    ``integration`` opt out entirely — those are the ones that may legitimately
    want a real daemon.
    """
    if request.node.get_closest_marker("integration"):
        yield
        return

    real_run = subprocess.run

    def guard(cmd, *args, **kwargs):
        argv = cmd if isinstance(cmd, (list, tuple)) else [cmd]
        if not argv or argv[0] != "docker":
            return real_run(cmd, *args, **kwargs)
        text_mode = bool(
            kwargs.get("text")
            or kwargs.get("universal_newlines")
            or kwargs.get("encoding")
        )
        empty = "" if text_mode else b""
        message = (
            "Error response from daemon: No such container: "
            "<docker disabled in tests>"
        )
        return subprocess.CompletedProcess(
            args=list(argv),
            returncode=1,
            stdout=empty,
            stderr=message if text_mode else message.encode(),
        )

    with patch.object(subprocess, "run", guard):
        yield


@pytest.fixture()
def mock_cfg():
    """Minimal Config-like object for testing."""
    cfg = MagicMock()
    cfg.deployment_name = "mylab"
    cfg.environment = "dev"
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
