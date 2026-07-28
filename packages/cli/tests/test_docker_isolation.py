"""Regression tests for the `no_real_docker` autouse guard in conftest.

The CLI drives `docker` against fixed container names, and some of those
commands mutate state — `_disable_funnel` runs `tailscale funnel --https=443
off` on `lablink-allocator-tailscale`, register can `docker rm -f
lablink-client`. Without isolation, running the unit suite on a machine with a
live LabLink stack silently broke that deployment: Funnel went off and the
public URL stopped serving, while the test run reported 101 passed.

These tests pin the guard so that protection cannot be quietly lost.
"""

import subprocess

from unittest.mock import MagicMock, patch


def test_docker_commands_never_reach_the_real_daemon():
    result = subprocess.run(
        ["docker", "ps"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 1
    assert "docker disabled in tests" in result.stderr


def test_state_mutating_docker_commands_are_intercepted_too():
    """The dangerous ones, named explicitly: turning off a live deployment's
    Funnel, and force-removing a registered client's container."""
    for argv in (
        ["docker", "exec", "lablink-allocator-tailscale",
         "tailscale", "funnel", "--https=443", "off"],
        ["docker", "rm", "-f", "lablink-client"],
        ["docker", "compose", "up", "-d"],
    ):
        result = subprocess.run(argv, capture_output=True, text=True, check=False)
        assert result.returncode == 1, argv
        assert "docker disabled in tests" in result.stderr, argv


def test_guard_respects_bytes_mode():
    """register.py calls `docker start` without text=True and decodes stderr
    itself, so the guard must hand back bytes there."""
    result = subprocess.run(["docker", "start", "x"], capture_output=True, check=False)
    assert isinstance(result.stderr, bytes)
    assert b"docker disabled in tests" in result.stderr


def test_non_docker_commands_still_run():
    result = subprocess.run(
        ["echo", "hello"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "hello"


def test_disable_funnel_is_a_silent_noop_under_the_guard():
    """_disable_funnel is documented best-effort, so the not-found result the
    guard returns must leave it silent rather than erroring."""
    from lablink_cli.commands.deploy_compose import _disable_funnel

    _disable_funnel()  # must not raise


def test_tailscale_state_volume_lookup_is_deterministic(tmp_path):
    """Unmocked, this read the developer's real volumes — so whether a test
    saw an existing <name>_tailscale_state depended on their machine."""
    from lablink_cli.commands.deploy_compose import _tailscale_state_volume_exists

    assert _tailscale_state_volume_exists(tmp_path / "sleap-lablink") is False


def test_explicit_patches_still_take_precedence():
    """Tests that mean to exercise a docker-invoking helper patch
    subprocess.run in their own module; that must win over the guard."""
    from lablink_cli.commands import deploy_compose as dc

    with patch.object(dc.subprocess, "run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        dc._disable_funnel()
        assert mock_run.call_args[0][0] == [
            "docker", "exec", "lablink-allocator-tailscale",
            "tailscale", "funnel", "--https=443", "off",
        ]
