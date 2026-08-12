"""Tests for `lablink client reset-overlay`.

Discarding the persisted overlay node identity is deliberately its own
command rather than part of `unregister`: removing the volume does NOT
remove the node from the tailnet (the coordination server keeps its record
and the offline machine keeps holding its MagicDNS name), so it guarantees
the next `register` is handed a suffixed name — the lablink#404 failure.
That is occasionally what an operator wants, but it must be opt-in.
"""
from __future__ import annotations

import pytest

from lablink_cli.commands.reset_overlay import run_reset_overlay
from lablink_cli.docker import Docker, DockerUnavailable, Result


class FakeDocker(Docker):
    def __init__(
        self,
        *,
        volumes=(),
        status="missing",
        rm=Result(0),
        unavailable=False,
    ):
        self._volumes = set(volumes)
        self._status = status
        self._rm = rm
        self._unavailable = unavailable
        self.removed = []

    def available(self):
        return not self._unavailable

    def require(self):
        if self._unavailable:
            raise DockerUnavailable()
        return None

    def container_status(self, name):
        return self._status

    def volume_exists(self, name):
        return name in self._volumes

    def remove_volume(self, name):
        self.removed.append(name)
        return self._rm


def test_aborts_when_docker_missing(capsys):
    with pytest.raises(SystemExit) as exc:
        run_reset_overlay(yes=True, docker=FakeDocker(unavailable=True))

    assert exc.value.code == 1
    assert "docker" in capsys.readouterr().out.lower()


def test_refuses_while_container_still_exists(capsys):
    """Docker will not remove a volume that is still attached, and tearing
    the container down is unregister's job — so point there instead of
    half-doing it."""
    with pytest.raises(SystemExit) as exc:
        run_reset_overlay(yes=True, docker=FakeDocker(status="running"))

    assert exc.value.code == 1
    assert "unregister" in capsys.readouterr().out


def test_noop_when_volume_absent(capsys):
    fake = FakeDocker(status="missing")

    run_reset_overlay(yes=True, docker=fake)

    assert fake.removed == [], (
        f"must not attempt removal when the volume is absent; got "
        f"{fake.removed}"
    )
    assert "Nothing to reset" in capsys.readouterr().out


def test_removes_volume_and_explains_the_stale_node(capsys):
    """The name is only freed by deleting the node in the admin console, so
    the output has to say so — otherwise the operator resets, re-registers,
    gets a suffixed name anyway, and has no idea why."""
    from lablink_cli.commands.register import TAILSCALE_STATE_VOLUME

    fake = FakeDocker(volumes={TAILSCALE_STATE_VOLUME})

    run_reset_overlay(yes=True, docker=fake)

    assert fake.removed == [TAILSCALE_STATE_VOLUME]
    out = capsys.readouterr().out
    assert "login.tailscale.com/admin/machines" in out


def test_prompt_abort_leaves_volume_alone(monkeypatch, capsys):
    from lablink_cli.commands.register import TAILSCALE_STATE_VOLUME

    fake = FakeDocker(volumes={TAILSCALE_STATE_VOLUME})
    monkeypatch.setattr("typer.confirm", lambda *a, **kw: False)

    run_reset_overlay(yes=False, docker=fake)

    assert fake.removed == []
    assert "Aborted" in capsys.readouterr().out


def test_daemon_error_aborts(capsys):
    with pytest.raises(SystemExit) as exc:
        run_reset_overlay(yes=True, docker=FakeDocker(status="daemon_error"))

    assert exc.value.code == 1
    assert "daemon" in capsys.readouterr().out.lower()


def test_reset_overlay_removes_the_volume(monkeypatch):
    from lablink_cli.commands.register import TAILSCALE_STATE_VOLUME

    fake = FakeDocker(volumes={TAILSCALE_STATE_VOLUME})
    run_reset_overlay(yes=True, docker=fake)
    assert fake.removed == [TAILSCALE_STATE_VOLUME]


def test_reset_overlay_exits_when_remove_fails():
    from lablink_cli.commands.register import TAILSCALE_STATE_VOLUME

    fake = FakeDocker(
        volumes={TAILSCALE_STATE_VOLUME},
        rm=Result(1, stderr="volume is in use"),
    )
    with pytest.raises(SystemExit):
        run_reset_overlay(yes=True, docker=fake)
