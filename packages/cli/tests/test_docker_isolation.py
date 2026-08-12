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
    guard returns must leave it silent rather than erroring. deploy_compose
    now reaches the guard indirectly, through the default `Docker` adapter's
    own `subprocess.run` call rather than one of its own."""
    from lablink_cli.commands.deploy_compose import _disable_funnel
    from lablink_cli.docker import default_docker

    _disable_funnel(docker=default_docker())  # must not raise


def test_tailscale_state_volume_lookup_is_deterministic(tmp_path):
    """Unmocked, this read the developer's real volumes — so whether a test
    saw an existing <name>_tailscale_state depended on their machine."""
    from lablink_cli.commands.deploy_compose import _tailscale_state_volume_exists
    from lablink_cli.docker import default_docker

    assert (
        _tailscale_state_volume_exists(
            tmp_path / "sleap-lablink", docker=default_docker()
        )
        is False
    )


def test_explicit_subprocess_patch_overrides_the_autouse_guard():
    """Guard-precedence invariant: a test's own explicit patch of the real
    `subprocess.run` still wins over the autouse guard's blanket patch. Now
    that deploy_compose has no `subprocess` reference of its own, the one
    place a docker call still reaches `subprocess.run` is inside the
    `Docker` adapter — so drive a real helper through `default_docker()`
    (not an injected fake) to keep the guard genuinely in the path, and
    patch `lablink_cli.docker.subprocess.run` around it. If the guard ever
    stopped yielding precedence to an explicit patch like this, every test
    that patches "the docker call" to return specific output would
    silently see the guard's canned not-found result instead."""
    from unittest.mock import MagicMock, patch

    from lablink_cli.commands.deploy_compose import _disable_funnel
    from lablink_cli.docker import default_docker

    with patch("lablink_cli.docker.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        _disable_funnel(docker=default_docker())
        assert mock_run.call_args[0][0] == [
            "docker", "exec", "lablink-allocator-tailscale",
            "tailscale", "funnel", "--https=443", "off",
        ]


def test_docker_fake_still_takes_precedence():
    """Now that deploy_compose is fully migrated onto the `Docker` adapter,
    a test that injects its own fake bypasses the guard entirely —
    dependency injection replaces subprocess-patching as the way a test
    controls docker behavior instead of relying on the guard's blanket
    not-found result."""
    from lablink_cli.commands.deploy_compose import _disable_funnel
    from lablink_cli.docker import Docker, Result

    class _RecordingDocker(Docker):
        def __init__(self):
            self.exec_calls = []

        def exec_in(self, container, argv):
            self.exec_calls.append(list(argv))
            return Result(0)

    fake = _RecordingDocker()
    _disable_funnel(docker=fake)
    assert fake.exec_calls == [
        ["tailscale", "funnel", "--https=443", "off"],
    ]
