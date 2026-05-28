"""`lablink client unregister` — tear down a registered BYO box."""

from __future__ import annotations

import shutil
import ssl
import subprocess
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import typer
from rich.console import Console

DEFAULT_ENV_FILE = Path.home() / ".lablink" / "client.env"


def run_unregister(
    *,
    env_file: Optional[Path],
    insecure: bool,
    yes: bool,
) -> None:
    """Best-effort allocator notify, then local cleanup. Always exits 0
    once the user has confirmed; partial failures don't block."""
    console = Console()
    env_file = env_file or DEFAULT_ENV_FILE

    if not env_file.exists():
        console.print("Nothing to unregister.")
        return

    env = _parse_env_file(env_file)
    required = ("CLIENT_ID", "CLIENT_SECRET", "ALLOCATOR_URL")
    missing = [k for k in required if not env.get(k)]
    if missing:
        console.print(
            f"[red]{env_file} is missing required keys: "
            f"{', '.join(missing)}.[/red]\n"
            f"Delete {env_file} manually and re-run "
            "`lablink client register` to recover."
        )
        raise SystemExit(1)

    if not yes:
        confirmed = typer.confirm(
            f"Remove lablink-client container and {env_file}?",
            default=False,
        )
        if not confirmed:
            console.print("Aborted.")
            return

    # Best-effort allocator notify
    notified = _notify_deregister(
        allocator_url=env["ALLOCATOR_URL"],
        client_id=env["CLIENT_ID"],
        client_secret=env["CLIENT_SECRET"],
        insecure=insecure,
        console=console,
    )
    if not notified:
        console.print(
            "[yellow]Allocator notify failed (allocator may already "
            "be torn down). Continuing local cleanup.[/yellow]"
        )

    # Docker container removal
    if shutil.which("docker") is None:
        console.print(
            "[yellow]docker not on PATH — skipping container "
            "removal. Remove `lablink-client` manually if it ever "
            "comes back.[/yellow]"
        )
    else:
        _exec_docker_rm(console)

    # Env file deletion (terminal step)
    try:
        env_file.unlink()
    except OSError as e:
        console.print(
            f"[red]Failed to delete {env_file}: {e}.[/red] "
            "Remove it manually."
        )
        raise SystemExit(1) from e

    console.print(
        f"[green]Unregistered.[/green] Removed {env_file} and the "
        "`lablink-client` container (if it was running)."
    )


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE env file. Lines starting with '#' or
    empty are ignored. No quoting/escaping — mirrors what
    `register.py` writes."""
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        result[k.strip()] = v.strip()
    return result


def _notify_deregister(
    *,
    allocator_url: str,
    client_id: str,
    client_secret: str,
    insecure: bool,
    console: Console,
) -> bool:
    """Best-effort DELETE /api/v1/clients/<client_id>.

    Returns True if the allocator returned 200, False on any other
    outcome (connection refused, timeout, 4xx, 5xx). Never raises —
    the caller continues regardless.
    """
    url = f"{allocator_url.rstrip('/')}/api/v1/clients/{client_id}"
    req = Request(url, method="DELETE")
    req.add_header("Authorization", f"Bearer {client_secret}")
    req.add_header("Accept", "application/json")

    ctx = ssl.create_default_context()
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    try:
        # S310: allocator URL is operator-supplied by design.
        with urlopen(req, timeout=5, context=ctx) as resp:  # noqa: S310
            return 200 <= resp.status < 300
    except HTTPError as e:
        if e.code == 404:
            # Row already gone — idempotent success.
            return True
        console.print(
            f"[yellow]Allocator returned {e.code}.[/yellow]"
        )
        return False
    except URLError as e:
        console.print(
            f"[yellow]Allocator unreachable: {e.reason}.[/yellow]"
        )
        return False
    except (TimeoutError, OSError) as e:
        console.print(
            f"[yellow]Allocator notify failed: {e}.[/yellow]"
        )
        return False


def _exec_docker_rm(console: Console) -> bool:
    """Run `docker rm -f lablink-client`. Returns True on success or
    when the container is already absent. Never raises.

    `docker rm -f` exits 0 in both cases — the only non-zero exits
    are for daemon-level failures (docker daemon down, permissions,
    etc.), which we surface as a yellow warning and continue.
    """
    try:
        result = subprocess.run(
            ["docker", "rm", "-f", "lablink-client"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as e:
        console.print(f"[yellow]docker rm failed: {e}.[/yellow]")
        return False
    if result.returncode == 0:
        return True
    stderr = (result.stderr or "").strip()
    console.print(
        f"[yellow]docker rm exited {result.returncode}: "
        f"{stderr or '(no stderr)'}.[/yellow]"
    )
    return False
