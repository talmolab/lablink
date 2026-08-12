"""The CLI's single seam onto the `docker` binary.

Every docker invocation in this package goes through here. Two reasons:

1. The "returncode != 0 means not-found" convention lives once instead of
   being re-derived at each call site.
2. Tests substitute :class:`NullDocker` instead of monkeypatching the global
   ``subprocess.run`` — which is what the old ``tests/conftest.py`` guard did,
   after a green test run silently turned a live deployment's Funnel off.

Verbs return domain values. The three escape hatches — :meth:`Docker.compose`,
:meth:`Docker.exec_in`, :meth:`Docker.run_detached` — return a raw
:class:`Result` because their callers format messages from both the exit code
and stderr.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

ContainerStatus = Literal[
    "running", "restarting", "exited", "missing", "daemon_error"
]

DOCKER_MISSING_MESSAGE = (
    "docker not found on PATH. Install Docker Engine + the Compose plugin "
    "(https://docs.docker.com/engine/install/) and re-run."
)

_INSPECT_TIMEOUT_S = 10


class DockerUnavailable(RuntimeError):
    """Raised when the `docker` binary is not on PATH."""

    def __init__(self, message: str = DOCKER_MISSING_MESSAGE) -> None:
        super().__init__(message)


class DockerDaemonError(RuntimeError):
    """Raised when the docker daemon cannot answer a query."""


@dataclass(frozen=True)
class Result:
    """The outcome of a raw docker invocation."""

    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        """True if docker exited zero."""
        return self.returncode == 0


class Docker:
    """Runs real `docker` commands."""

    def path(self) -> str | None:
        """Absolute path to the docker binary, or None if not on PATH."""
        return shutil.which("docker")

    def available(self) -> bool:
        """True if the docker binary is on PATH."""
        return self.path() is not None

    def require(self) -> None:
        """Raise :class:`DockerUnavailable` if docker is not on PATH."""
        if not self.available():
            raise DockerUnavailable()

    # -- verbs ---------------------------------------------------------

    def container_status(self, name: str) -> ContainerStatus:
        """Map ``docker inspect`` output to a coarse status.

        - "running"     -> container is up
        - "restarting"  -> docker is bringing it back
        - "exited"      -> container is stopped
        - "missing"     -> no container with that name exists
        - "daemon_error"-> docker daemon is unreachable
        """
        try:
            result = subprocess.run(
                ["docker", "inspect", name, "--format", "{{.State.Status}}"],
                capture_output=True,
                text=True,
                timeout=_INSPECT_TIMEOUT_S,
            )
        except (subprocess.TimeoutExpired, OSError):
            return "daemon_error"

        if result.returncode == 0:
            status = result.stdout.strip()
            if status in ("running", "restarting", "exited"):
                return status  # type: ignore[return-value]
            # Other statuses (created, paused, dead) — treat like exited.
            return "exited"

        stderr = (result.stderr or "").lower()
        if "no such" in stderr or "no such object" in stderr:
            return "missing"
        return "daemon_error"

    def inspect_format(self, name: str, template: str) -> str:
        """Return a Go-template field from ``docker inspect``.

        Empty string when the object is absent or the template matched
        nothing — callers treat both the same way.
        """
        self.require()
        result = subprocess.run(
            ["docker", "inspect", name, "--format", template],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    def daemon_info(self, template: str) -> str:
        """Return a Go-template field from ``docker info``.

        Raises :class:`DockerDaemonError` if the daemon cannot answer.
        """
        self.require()
        try:
            result = subprocess.run(
                ["docker", "info", "--format", template],
                capture_output=True,
                text=True,
                check=True,
                timeout=_INSPECT_TIMEOUT_S,
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            OSError,
        ) as e:
            raise DockerDaemonError(str(e)) from e
        return result.stdout.strip()

    def volume_exists(self, name: str) -> bool:
        """True if the named volume is present.

        ``docker volume inspect`` exits non-zero for an unknown volume,
        which is the only signal needed.
        """
        self.require()
        result = subprocess.run(
            ["docker", "volume", "inspect", name],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    def remove_volume(self, name: str) -> Result:
        """Remove a volume. Callers format their own failure message."""
        self.require()
        return self._run(["docker", "volume", "rm", name])

    def remove_container(self, name: str, *, force: bool = True) -> Result:
        """Remove a container.

        ``docker rm -f`` exits 0 whether or not the container existed; a
        non-zero exit is a daemon-level failure.
        """
        self.require()
        argv = ["docker", "rm"]
        if force:
            argv.append("-f")
        argv.append(name)
        return self._run(argv)

    def start_container(self, name: str) -> Result:
        """Start an existing, stopped container."""
        self.require()
        return self._run(["docker", "start", name])

    def logs(
        self,
        name: str,
        *,
        tail: int | None = None,
        merge_stderr: bool = False,
        timeout: float | None = None,
    ) -> Result:
        """Snapshot a container's logs.

        ``merge_stderr`` folds stderr into stdout. Needed wherever the
        container's Python logging goes to stderr: capturing the streams
        separately and reading only stdout hides exactly the tracebacks the
        caller is looking for.

        No ``require()`` guard — like :meth:`container_status`, a missing
        binary already falls out of the ``except (TimeoutExpired, OSError)``
        below (``FileNotFoundError`` is an ``OSError``) as an ordinary
        failed ``Result``. Adding ``require()`` would only turn that
        swallowed error into a raised ``DockerUnavailable``, which is what
        callers relied on *not* happening pre-refactor.
        """
        argv = ["docker", "logs"]
        if tail is not None:
            argv += ["--tail", str(tail)]
        argv.append(name)

        kwargs: dict = {"text": True, "check": False}
        if merge_stderr:
            kwargs["stdout"] = subprocess.PIPE
            kwargs["stderr"] = subprocess.STDOUT
        else:
            kwargs["capture_output"] = True
        if timeout is not None:
            kwargs["timeout"] = timeout

        try:
            result = subprocess.run(argv, **kwargs)
        except (subprocess.TimeoutExpired, OSError) as e:
            return Result(returncode=1, stderr=str(e))
        return Result(
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )

    def follow_logs(
        self, name: str, *, since: str | None = None
    ) -> subprocess.Popen:
        """Spawn ``docker logs --follow --timestamps [--since <ts>] <name>``.

        Returns the Popen handle: the log shipper needs ``.terminate()`` and
        ``.poll()`` as well as incremental reads from ``.stdout``.
        """
        self.require()
        argv = ["docker", "logs", "--follow", "--timestamps"]
        if since:
            argv += ["--since", since]
        argv.append(name)
        return subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # line-buffered
        )

    # -- escape hatches ------------------------------------------------

    def compose(
        self,
        workdir: Path | str | None,
        *args: str,
        capture: bool = True,
    ) -> Result:
        """Run ``docker compose <args>`` in ``workdir``.

        ``workdir`` is explicit rather than ambient process cwd. Pass None
        for subcommands that are not tied to a deployment directory
        (``docker compose version``). ``capture=False`` streams output to the
        terminal, which is what the deploy/destroy paths want.
        """
        self.require()
        return self._run(
            ["docker", "compose", *args], cwd=workdir, capture=capture
        )

    def exec_in(self, container: str, argv: Sequence[str]) -> Result:
        """Run a command inside a running container."""
        self.require()
        return self._run(["docker", "exec", container, *argv])

    def run_detached(self, argv: Sequence[str]) -> Result:
        """Run a fully-formed ``docker run`` argv, streaming to the terminal.

        Output is not captured — image pull progress is meant to be visible —
        so the returned Result carries only the exit code.
        """
        self.require()
        return self._run(list(argv), capture=False)

    # -- internals -----------------------------------------------------

    def _run(
        self,
        argv: list[str],
        *,
        cwd: Path | str | None = None,
        capture: bool = True,
    ) -> Result:
        try:
            result = subprocess.run(
                argv,
                cwd=cwd,
                capture_output=capture,
                text=True,
                check=False,
            )
        except OSError as e:
            return Result(returncode=1, stderr=str(e))
        return Result(
            returncode=result.returncode,
            stdout=result.stdout or "",
            stderr=result.stderr or "",
        )


class NullDocker(Docker):
    """Answers every call as a machine with no such container or volume.

    This is what tests get by default. It is the honest model for a
    unit-test environment and it is what the callers already handle:
    best-effort teardown stays silent, existence checks report False.
    """

    _NOT_FOUND = (
        "Error response from daemon: No such container: "
        "<docker disabled in tests>"
    )

    def path(self) -> str | None:
        return None

    def available(self) -> bool:
        return False

    def require(self) -> None:
        return None

    def container_status(self, name: str) -> ContainerStatus:
        return "missing"

    def inspect_format(self, name: str, template: str) -> str:
        return ""

    def daemon_info(self, template: str) -> str:
        raise DockerDaemonError(self._NOT_FOUND)

    def volume_exists(self, name: str) -> bool:
        return False

    def logs(
        self,
        name: str,
        *,
        tail: int | None = None,
        merge_stderr: bool = False,
        timeout: float | None = None,
    ) -> Result:
        return Result(returncode=1, stderr=self._NOT_FOUND)

    def follow_logs(
        self, name: str, *, since: str | None = None
    ) -> subprocess.Popen:
        raise DockerUnavailable(self._NOT_FOUND)

    def _run(
        self,
        argv: list[str],
        *,
        cwd: Path | str | None = None,
        capture: bool = True,
    ) -> Result:
        return Result(returncode=1, stderr=self._NOT_FOUND)


_default: Docker | None = None


def default_docker() -> Docker:
    """The process-wide default adapter.

    Tests replace the module attribute ``_default`` rather than patching
    ``subprocess``.
    """
    global _default
    if _default is None:
        _default = Docker()
    return _default
