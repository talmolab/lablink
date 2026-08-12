# Bring-Your-Own Clients

The CLI's other deployment mode. Instead of provisioning EC2 instances, the
allocator runs as a **local docker-compose stack** on a machine you already have,
and the client machines are boxes you register yourself. No AWS account, no
OpenTofu, no cloud bill.

Set `provider: manual` in your config and every command in the
[CLI Reference](../reference/cli.md) switches to this path.

Beyond the split in [CLI Overview](index.md#two-providers), the practical
differences:

| | AWS provider | Manual provider |
|---|---|---|
| Needs OpenTofu | Yes | No |
| Needs docker locally | No | **Yes** (allocator + clients are containers) |
| Cost | Per-hour EC2 + EBS + optional ALB | Your own hardware |

Good fits: a lab with GPU workstations already on a bench, a workshop on
institution-owned machines, or a scheduler-hosted workload (e.g. Run:AI) you can't
provision from OpenTofu.

## Prerequisites

- **docker** and the **`docker compose` v2 plugin** on the allocator host and on every client box.
- The CLI installed — see [Installation](installation.md).
- A network path from each client box to the allocator, or from the allocator to each client. Which direction you need is what [connectivity mode](#pick-a-connectivity-mode) decides.

`lablink doctor` checks the docker side for you under this provider. Once a box is
registered, `lablink client doctor` checks that box's own health — registration,
container, and log shipper. See the
[CLI Reference](../reference/cli.md#client-doctor).

## Pick a connectivity mode

`manual.connectivity` decides how a participant's browser reaches a client's
KasmVNC desktop. This is the one decision worth making before you deploy, because
it determines how each box registers and whether off-LAN participants can work at
all.

| Mode | How the desktop is reached | Use when |
|---|---|---|
| `lan_direct` (default) | The browser opens a WebSocket straight to the client's LAN IP. | Every client *and* every participant is on the allocator's own LAN. |
| `mesh_overlay` | The client joins a Tailscale tailnet; the allocator reaches it over the overlay and proxies the byte path through its own nginx. | Clients aren't on the allocator's LAN — e.g. a Run:AI-hosted workload. |
| `reverse_tunnel` | The client dials **out** to the allocator and holds one connection open. | The network won't carry Tailscale, or the box can't accept inbound connections at all. |

!!! warning "`lan_direct` cannot serve off-LAN participants"
    If participants are remote, pick `mesh_overlay` or `reverse_tunnel` —
    `lan_direct` combined with any exposure mode is rejected, and
    [Configuration](../configuration.md#manual-provider-options-manual) explains why.

Reaching the **allocator** from off-LAN is a separate axis —
`manual.participant_exposure`, covered on that same page.

## Step 1: Configure

```bash
lablink configure
```

The wizard writes `~/.lablink/config.yaml`. Choose the manual provider, then the
connectivity mode. Unlike the AWS path, it does **not** run `lablink setup`
afterwards — there is no remote state to bootstrap.

!!! note "The manual provider requires `ssl.provider: none`"
    The allocator image ships no TLS terminator — on the AWS path, Caddy is part of
    the infrastructure, not the container. `lablink deploy` exits with an error if
    `ssl.provider` is anything but `none`.

    The wizard handles this for you: picking the manual provider pins
    `ssl.provider: none`, disables DNS, and skips the DNS/SSL screen entirely. The
    error is only reachable from a **hand-edited** config — worth knowing, because
    `SSLConfig`'s own default is `letsencrypt`, so a config you wrote yourself or
    inherited from an AWS deployment will hit it.

    For public TLS, either use a
    [participant exposure mode](../configuration.md#exposure-mode-cloudflare_tunnel)
    (which terminates TLS for you) or front the compose stack with your own reverse
    proxy.

A minimal LAN-only config:

```yaml
provider: manual
deployment_name: smith-lab
ssl:
  provider: none
manual:
  connectivity: lan_direct
```

## Step 2: Sanity check

```bash
lablink doctor
```

## Step 3: Deploy the allocator

```bash
lablink deploy
```

This renders `docker-compose.yml`, a `.env`, and a copy of your `config.yaml` into
`~/.lablink/compose/<deployment_name>/`, then runs `docker compose up -d` and waits
for the allocator's health endpoint. Postgres runs inside the same stack, with its
data in a named volume.

You'll be prompted for an admin username and password, which are not written to
`config.yaml`.

When it finishes, `deploy` prints what you need to onboard boxes:

```text
Deployment complete.
  Allocator URL (local): http://localhost
  Allocator URL (LAN):   http://192.168.1.42
  Admin user:            admin
  Register token:        Xf3k9…

Next step: on each BYO box on the same LAN, run
  lablink client register --allocator-url http://192.168.1.42 --register-token Xf3k9…
```

The printed `client register` command is already tailored to your connectivity
mode — mesh-overlay and reverse-tunnel deployments get the extra flags filled in.
Copy it as-is.

!!! tip "Lost the token?"
    ```bash
    docker logs lablink-allocator 2>&1 | grep REGISTER_TOKEN
    ```
    The `2>&1` matters — the allocator logs to stderr, so without it `grep` sees
    nothing.

If `deploy` could only detect `localhost` and not a LAN address, the command it
prints is valid only for a client on the allocator host itself. Substitute the
host's real LAN IP or hostname before handing it to anyone else.

Deploying with a connectivity or exposure mode that needs Tailscale also requires
an auth key on the **first** deploy:

```bash
lablink deploy --tailscale-authkey tskey-auth-...
```

Redeploys carry the previous key forward from the deployment's `.env`, so you only
pass it again to rotate it.

## Step 4: Register each box

Run this **on the machine you're adding**, not on the allocator host:

```bash
lablink client register \
  --allocator-url http://192.168.1.42:5000 \
  --register-token Xf3k9…
```

It auto-detects hostname, LAN IP, machine identity, and GPU presence/model, writes
the returned secrets to `~/.lablink/client.env` (mode `0600`), and `docker run`s the
client container. Every auto-detected value has an override flag if you need one.

The registration shape has to match the allocator's configured connectivity, or the
allocator rejects it with a 400 — see
[`client register`](../reference/cli.md#client-register) for which flags each mode
requires.

The allocator's admin UI also renders a ready-to-paste command at
**`/admin/byo-onboarding`**, with the flags already matched to your mode. That's the
easiest thing to send to someone else who owns a box.

!!! note "Registering ahead of time, from somewhere else"
    For mesh-overlay and reverse-tunnel clients, `register` defaults to running the
    container right here (`--run-locally`). Add `--no-run-locally` to instead print
    the secrets for pasting into a separate workload submission — useful when you're
    registering a scheduler-hosted workload from your laptop rather than from inside
    the workload. In that case you must also pass `--hostname` and
    `--machine-identity`, since there's nothing local to auto-detect from.

If docker is missing on the box, `register` keeps the env file so you can install
docker and re-run with `--force`.

Confirm the box landed in the pool:

```bash
lablink status
```

## Day-to-day

| Task | Command | Manual-provider notes |
|---|---|---|
| Check health | `lablink status` | Shows compose container status + the allocator's health endpoint. No cost estimate — the hardware is yours. |
| Read logs | `lablink logs` | Tails the local `lablink-allocator` container. Per-VM client logs aren't centralized in this mode — run `docker logs lablink-client` on the box itself. |
| Add a box | `lablink client register` | Run on the new box. |
| Remove a box | `lablink client unregister` | Run on that box. |

Only `client launch` is unavailable — it no-ops with a message pointing you back at
`client register`. Every other command, `stats` and `export-metrics` included,
behaves as it does on the AWS path.

## Removing a box

On the box itself:

```bash
lablink client unregister
```

Notifies the allocator best-effort, removes the `lablink-client` container, and
deletes the env file. It's idempotent and safe to run after the allocator is already
gone.

For a mesh-overlay client, `unregister` deliberately **keeps** the Tailscale node
identity so re-registering returns to the same tailnet node under the same name. To
deliberately start fresh:

```bash
lablink client reset-overlay
```

!!! warning "Reset does not delete the old tailnet machine"
    The previous node goes offline still holding its name, so the next join gets a
    numeric suffix (`-1`, `-2`, …) until you delete the stale machine in the
    Tailscale admin console. The container must already be removed, too — docker
    won't detach a volume that's in use.

## Tearing down

```bash
lablink destroy              # stops the stack, wipes the Postgres volume
lablink destroy --keep-data  # stops the stack, preserves registration history
```

`--keep-data` is the one to use between sessions of the same workshop — sessions and
registration history survive the next `lablink deploy`.

To also remove the compose working directory and its volumes outright:

```bash
lablink cleanup
```

Under the manual provider this runs `docker compose down --volumes` and deletes
`~/.lablink/compose/<deployment_name>/`. (`--dry-run` is AWS-only; the manual path
confirms interactively instead.)

## Next steps

- [Configuration](../configuration.md#manual-provider-options-manual) — every `manual.*` setting, including how to publish the allocator to off-LAN participants.
- [CLI Reference](../reference/cli.md#client-fleet-commands) — full flag list for the `client` commands.
- [Troubleshooting](../troubleshooting.md) — general LabLink issues.
