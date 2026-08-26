"""`lablink client reset-overlay` — discard this box's persisted overlay
node identity.

Separate from `unregister` on purpose. `unregister` keeps the identity so
that unregister/register lands back on the same tailnet node with the same
MagicDNS name. Removing it is the opposite intent — "let this box join as a
brand-new node next time" — and it has a consequence that has to be stated
out loud rather than buried in a teardown path:

Deleting the local state does NOT delete the machine from the tailnet. The
coordination server keeps its own record, the machine simply goes offline,
and it *keeps holding its MagicDNS name*. So the next `register` mints a new
node which cannot claim that name and is handed a suffixed one
(`...-gpu-1` -> `...-gpu-1-1`). Freeing the name requires deleting the stale
node in the Tailscale admin console. This command therefore says so.

The client reports whatever name it actually got back to the allocator (see
client/start.sh), so a suffixed name is not broken — just untidy, and
untidiness here is what made lablink#404 hard to read.
"""

from __future__ import annotations

import typer
from rich.console import Console

from lablink_cli.commands.register import TAILSCALE_STATE_VOLUME
from lablink_cli.docker import Docker, DockerUnavailable, default_docker
from lablink_cli.commands.register import CONTAINER_NAME

TAILNET_ADMIN_URL = "https://login.tailscale.com/admin/machines"


def run_reset_overlay(*, yes: bool, docker: Docker | None = None) -> None:
    """Remove the persisted tailscaled state volume for the BYO client."""
    docker = docker or default_docker()
    console = Console()

    try:
        docker.require()
    except DockerUnavailable:
        console.print(
            "[red]docker is not on PATH.[/red] There is nothing for this "
            "command to remove without it."
        )
        raise SystemExit(1)

    status = docker.container_status(CONTAINER_NAME)
    if status == "daemon_error":
        console.print(
            "[red]Docker daemon is unreachable.[/red] Start Docker and "
            "re-run."
        )
        raise SystemExit(1)
    if status != "missing":
        # Docker refuses to remove a volume that is still attached, and
        # tearing the container down belongs to unregister — don't duplicate
        # it here and half-succeed.
        console.print(
            f"[red]The {CONTAINER_NAME} container still exists "
            f"(status: {status}).[/red]\n"
            "Docker will not remove a volume that is still attached. Run "
            "[bold]lablink client unregister[/bold] first (or "
            f"`docker rm -f {CONTAINER_NAME}`), then re-run this command."
        )
        raise SystemExit(1)

    if not docker.volume_exists(TAILSCALE_STATE_VOLUME):
        console.print(
            "Nothing to reset — no persisted overlay identity on this box."
        )
        return

    if not yes:
        confirmed = typer.confirm(
            f"Remove the {TAILSCALE_STATE_VOLUME} volume? The next "
            "`lablink client register` will join the tailnet as a new node.",
            default=False,
        )
        if not confirmed:
            console.print("Aborted.")
            return

    result = docker.remove_volume(TAILSCALE_STATE_VOLUME)
    if not result.ok:
        console.print(
            f"[red]Could not remove {TAILSCALE_STATE_VOLUME}: "
            f"{result.stderr.strip() or '(no stderr)'}[/red]"
        )
        raise SystemExit(1)

    console.print(
        f"[green]Removed {TAILSCALE_STATE_VOLUME}.[/green] The next "
        "`lablink client register` will join the tailnet as a new node."
    )
    # Said explicitly because it is the non-obvious half: the operator has
    # just discarded the local identity, but the old machine is still in the
    # tailnet holding the name, so the new node gets a numeric suffix until
    # that machine is deleted. Silence here is what makes the suffix look
    # like a typo rather than a rename (lablink#404).
    console.print(
        "\n[yellow]This does not remove the old machine from your "
        "tailnet.[/yellow] It goes offline but keeps holding its MagicDNS "
        "name, so the new node will be given a numeric suffix (e.g. "
        "[dim]-gpu-1[/dim] -> [dim]-gpu-1-1[/dim]) until you delete the "
        f"stale machine at:\n  {TAILNET_ADMIN_URL}\n"
        "The client reports whichever name it actually receives, so a "
        "suffixed name still works."
    )
