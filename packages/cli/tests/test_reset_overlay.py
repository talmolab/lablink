"""Tests for `lablink client reset-overlay`.

Discarding the persisted overlay node identity is deliberately its own
command rather than part of `unregister`: removing the volume does NOT
remove the node from the tailnet (the coordination server keeps its record
and the offline machine keeps holding its MagicDNS name), so it guarantees
the next `register` is handed a suffixed name — the lablink#404 failure.
That is occasionally what an operator wants, but it must be opt-in.
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

import pytest


def _completed(cmd, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def _mock_docker(status):
    """A `default_docker()` stand-in whose container_status is fixed."""
    docker = MagicMock()
    docker.container_status.return_value = status
    return docker


def test_aborts_when_docker_missing(capsys):
    from lablink_cli.commands.reset_overlay import run_reset_overlay

    with patch("lablink_cli.commands.reset_overlay.shutil.which",
               return_value=None):
        with pytest.raises(SystemExit) as exc:
            run_reset_overlay(yes=True)

    assert exc.value.code == 1
    assert "docker" in capsys.readouterr().out.lower()


def test_refuses_while_container_still_exists(capsys):
    """Docker will not remove a volume that is still attached, and tearing
    the container down is unregister's job — so point there instead of
    half-doing it."""
    from lablink_cli.commands.reset_overlay import run_reset_overlay

    with patch("lablink_cli.commands.reset_overlay.shutil.which",
               return_value="/usr/bin/docker"), \
         patch("lablink_cli.commands.reset_overlay.default_docker",
               return_value=_mock_docker("running")):
        with pytest.raises(SystemExit) as exc:
            run_reset_overlay(yes=True)

    assert exc.value.code == 1
    assert "unregister" in capsys.readouterr().out


def test_noop_when_volume_absent(capsys):
    from lablink_cli.commands.reset_overlay import run_reset_overlay

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        # `docker volume inspect` fails => no such volume.
        return _completed(cmd, returncode=1, stderr="no such volume")

    with patch("lablink_cli.commands.reset_overlay.shutil.which",
               return_value="/usr/bin/docker"), \
         patch("lablink_cli.commands.reset_overlay.default_docker",
               return_value=_mock_docker("missing")), \
         patch("lablink_cli.commands.reset_overlay.subprocess.run",
               side_effect=fake_run):
        run_reset_overlay(yes=True)

    assert not any("rm" in c for c in calls), (
        f"must not attempt removal when the volume is absent; got {calls}"
    )
    assert "Nothing to reset" in capsys.readouterr().out


def test_removes_volume_and_explains_the_stale_node(capsys):
    """The name is only freed by deleting the node in the admin console, so
    the output has to say so — otherwise the operator resets, re-registers,
    gets a suffixed name anyway, and has no idea why."""
    from lablink_cli.commands.register import TAILSCALE_STATE_VOLUME
    from lablink_cli.commands.reset_overlay import run_reset_overlay

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _completed(cmd, returncode=0)

    with patch("lablink_cli.commands.reset_overlay.shutil.which",
               return_value="/usr/bin/docker"), \
         patch("lablink_cli.commands.reset_overlay.default_docker",
               return_value=_mock_docker("missing")), \
         patch("lablink_cli.commands.reset_overlay.subprocess.run",
               side_effect=fake_run):
        run_reset_overlay(yes=True)

    assert ["docker", "volume", "rm", TAILSCALE_STATE_VOLUME] in calls
    out = capsys.readouterr().out
    assert "login.tailscale.com/admin/machines" in out


def test_prompt_abort_leaves_volume_alone(monkeypatch, capsys):
    from lablink_cli.commands.reset_overlay import run_reset_overlay

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _completed(cmd, returncode=0)

    monkeypatch.setattr("typer.confirm", lambda *a, **kw: False)

    with patch("lablink_cli.commands.reset_overlay.shutil.which",
               return_value="/usr/bin/docker"), \
         patch("lablink_cli.commands.reset_overlay.default_docker",
               return_value=_mock_docker("missing")), \
         patch("lablink_cli.commands.reset_overlay.subprocess.run",
               side_effect=fake_run):
        run_reset_overlay(yes=False)

    assert ["docker", "volume", "rm", TAILSCALE_STATE_VOLUME_NAME] not in calls
    assert "Aborted" in capsys.readouterr().out


TAILSCALE_STATE_VOLUME_NAME = "lablink-client-tailscale"


def test_daemon_error_aborts(capsys):
    from lablink_cli.commands.reset_overlay import run_reset_overlay

    with patch("lablink_cli.commands.reset_overlay.shutil.which",
               return_value="/usr/bin/docker"), \
         patch("lablink_cli.commands.reset_overlay.default_docker",
               return_value=_mock_docker("daemon_error")):
        with pytest.raises(SystemExit) as exc:
            run_reset_overlay(yes=True)

    assert exc.value.code == 1
    assert "daemon" in capsys.readouterr().out.lower()
