# CLI Reference

Complete reference for every `lablink` command. Grouped to match the `lablink --help` output.

!!! note "Manual reference"
    This page is hand-written from `packages/cli/src/lablink_cli/app.py`. For the authoritative help text, run `lablink <command> --help`. Auto-generated reference is planned once the package is published to PyPI.

## Global options

`lablink` itself takes only `--version` / `-v`. Everything else, including
`--config`, is a **per-command** option and goes *after* the command:

```bash
lablink deploy --config /path/to/config.yaml   # correct
lablink --config /path/to/config.yaml deploy   # error: No such option
```

Default config path: `~/.lablink/config.yaml`. If the file is missing, the command
exits with a hint to run `lablink configure`.

## Provider modes

Almost every command below branches on the `provider` field in your config; each
one notes its manual-provider behavior inline. For the two modes side by side see
[CLI Overview](../cli/index.md#two-providers), for the manual walkthrough
[Bring-Your-Own Clients](../cli/byo-clients.md), and for the `manual.*` settings
[Configuration](../configuration.md#manual-provider-options-manual).

---

## Setup commands

### `configure`

Create or edit the LabLink configuration.

```bash
lablink configure [--config PATH] [--template]
```

Launches a TUI wizard that generates or edits `config.yaml`. On an AWS-provider
config it then automatically runs [`setup`](#setup) to create the resources
OpenTofu needs for remote state (S3 bucket + DynamoDB lock table). Manual-provider
configs skip that step — there is nothing to bootstrap.

The wizard is idempotent: re-run it any time to edit a config, and it loads your
existing values as the defaults.

| Option | Description |
|---|---|
| `-c`, `--config PATH` | Path to `config.yaml`. Default: `~/.lablink/config.yaml`. |
| `--template` | Configure a [template repo](../quickstart-template.md) checkout instead of the local deployment. |

#### Configuring a template repo

`--template` points the same wizard at a
[lablink-template](https://github.com/talmolab/lablink-template) checkout, so
deployments driven by GitHub Actions get the TUI too rather than only the
`scripts/configure.sh` prompts. Run it from the repository root:

```bash
lablink configure --template
```

It differs from a normal run in three ways:

- Writes `lablink-infrastructure/config/config.yaml` — the file the OpenTofu
  Deploy workflow reads — instead of `~/.lablink/config.yaml`.
- Writes `PLACEHOLDER_ADMIN_PASSWORD` and `PLACEHOLDER_DB_PASSWORD` in place of
  real passwords, which the workflow substitutes with your `ADMIN_PASSWORD` and
  `DB_PASSWORD` repository secrets at deploy time. **The generated file is safe
  to commit; it never contains a password.**
- Skips the automatic [`setup`](#setup) step, because the template's
  `scripts/setup.sh` already created the state bucket and lock table.

Commit the result and push to deploy:

```bash
git add lablink-infrastructure/config/config.yaml
git commit -m "Update deployment configuration"
git push
```

!!! warning "Don't hand-edit the password fields"
    Leave the two `PLACEHOLDER_*` values exactly as written. The deploy workflow
    matches them literally, and its safety check only catches placeholders left
    *un*-substituted — a config with real-looking passwords in those fields
    passes the check and deploys without ever reading your secrets.

---

### `setup`

Provision provider-specific bootstrap resources.

```bash
lablink setup [--config PATH]
```

**AWS provider:** creates the S3 bucket (versioned + encrypted) and DynamoDB lock
table used for OpenTofu remote state. Automatically run during
[`configure`](#configure) — use this command on its own to recreate the resources
if they were deleted out of band.

**Manual provider:** a no-op. Prints a message explaining that the compose stack
needs no remote state and exits 0.

| Option | Description |
|---|---|
| `-c`, `--config PATH` | Path to `config.yaml`. |

---

### `doctor`

Check prerequisites and configuration.

```bash
lablink doctor
```

Takes no options. The checks it runs depend on the provider in your config:

**AWS provider** — six checks:

| Check | Passes when |
|---|---|
| OpenTofu installed | The `tofu` binary is on `PATH` |
| Config file | `config.yaml` exists at the resolved path |
| Config validates | The file merges cleanly against the schema |
| AWS credentials | STS can resolve an identity in the configured region |
| S3 state bucket | The OpenTofu state bucket exists |
| AMI for region | The CLI has an AMI mapping for the configured region |

**Manual provider** — checks that `docker` is on `PATH` and that the
`docker compose` v2 subcommand is available.

If no config is readable yet, `doctor` falls back to the AWS checks so it can still
tell you what's missing. Exit code is non-zero if any check fails.

---

## Deployment commands

### `deploy`

Deploy LabLink infrastructure (AWS OpenTofu or docker-compose).

```bash
lablink deploy [--config PATH] [--template-version V] [--terraform-bundle PATH] [--yes]
               [--tailscale-authkey KEY] [--cloudflare-tunnel-token TOKEN] [--render-only]
```

**AWS provider:** downloads the pinned `lablink-template` OpenTofu files (or uses a
cached / bundled copy), renders your config into OpenTofu variables, and runs
`tofu apply`.

**Manual provider:** renders a `docker-compose.yml`, a `.env`, and your
`config.yaml` into `~/.lablink/compose/<deployment_name>/` and runs
`docker compose up -d`. The stack is single-service (allocator + its internal
Postgres), plus a Tailscale sidecar when the configuration needs one. Postgres data
lives in a named volume.

Either way it prompts once for an admin username (default `admin`) and an admin
password. Neither is stored in `config.yaml` — they are passed to OpenTofu /
the container only.

| Option | Description |
|---|---|
| `-c`, `--config PATH` | Path to `config.yaml`. |
| `--template-version V` | Override the pinned template version (e.g. `v0.2.0`). Skips checksum verification. **AWS provider only.** |
| `--terraform-bundle PATH` | Path to a local template tarball for offline deploys. **AWS provider only.** |
| `-y`, `--yes` | Skip confirmation prompts. Does not bypass credential prompts (the admin password is still required interactively). |
| `--tailscale-authkey KEY` | Auth key for the allocator's own tailnet sidecar. Required on the **first** deploy when `manual.connectivity` is `mesh_overlay` and/or `manual.participant_exposure` is `tailscale_funnel`; optional on redeploys (the previous value is carried forward from the deployment's `.env`). **Manual provider only.** |
| `--cloudflare-tunnel-token TOKEN` | Token for publishing the allocator at `manual.public_hostname`. Required on the first deploy when `manual.participant_exposure` is `cloudflare_tunnel`; optional on redeploys. Supply it again to rotate. **Manual provider only.** |
| `--render-only` | Render the compose bundle and print a launch sheet instead of starting containers — for running the allocator image as a workload on an external container platform (Run:AI, Kubernetes) with no local Docker daemon. See [External Runtime](../cli/external-runtime.md). **Manual provider only.** |

Secrets passed via `--tailscale-authkey` / `--cloudflare-tunnel-token` are written
only to the deployment's `.env` (mode `0600`), never to `config.yaml`.

---

### `destroy`

Tear down LabLink infrastructure.

```bash
lablink destroy [--config PATH] [--yes] [--verbose] [--keep-data]
```

**AWS provider:** runs `tofu destroy` against the deployment's working
directory. Removes the allocator EC2 instance, security groups, key pair, and any
ALB/Route 53 records OpenTofu owns. Client VMs owned by the allocator are
destroyed along with it.

The S3 state bucket and DynamoDB lock table are **not** removed — reuse them on the
next deploy, or tear them down with [`cleanup`](#cleanup).

**Manual provider:** brings the compose stack down. By default this also wipes the
Postgres data volume.

| Option | Description |
|---|---|
| `-c`, `--config PATH` | Path to `config.yaml`. |
| `-y`, `--yes` | Skip confirmation prompts. Password prompts still appear. |
| `-v`, `--verbose` | Show the full OpenTofu output instead of a summary. |
| `--keep-data` | Preserve the Postgres data volume instead of the default full wipe, so registration history and sessions survive a later redeploy. **Manual provider only** — ignored for AWS. |

---

## Client fleet commands

`lablink client` groups everything that manages client machines.

```bash
lablink client --help
```

### `client launch`

Launch client VMs via the allocator service.

```bash
lablink client launch --num-vms N [--config PATH] [--verbose]
```

**AWS provider only.** Calls the allocator's create-VM endpoint; the allocator
provisions the VMs in its own OpenTofu workspace, so OpenTofu is not required
locally for this command.

Under the manual provider this command no-ops with a message pointing you at
[`client register`](#client-register).

| Option | Description |
|---|---|
| `-n`, `--num-vms N` | Number of client VMs to launch. **Required.** |
| `-c`, `--config PATH` | Path to `config.yaml`. |
| `-v`, `--verbose` | Show the full OpenTofu output instead of a summary. |

---

### `client destroy`

Destroy all client VMs via the allocator service.

```bash
lablink client destroy [--config PATH] [--yes] [--verbose]
```

**AWS provider only.** Calls the allocator's destroy endpoint; the allocator runs
`tofu destroy` over its own workspace, so OpenTofu is not required locally.

This is the CLI equivalent of the admin UI's **Delete Instances** page. It leaves
the allocator running — use [`destroy`](#destroy) to tear down the whole
deployment.

**Destructive.** Along with the VMs, this clears the allocator's `vms` table:
inventory, per-VM logs, and session history are gone. Anyone connected at the
time loses their session. Run
[`export-metrics`](#export-metrics) with `--allocator` first if you need the
numbers. Prompts for confirmation unless `--yes` is passed.

If no client VMs were ever launched the command reports that and exits 0, so it
is safe to re-run.

Under the manual provider this command no-ops with a message pointing you at
[`client unregister`](#client-unregister).

| Option | Description |
|---|---|
| `-c`, `--config PATH` | Path to `config.yaml`. |
| `-y`, `--yes` | Skip the confirmation prompt. Password prompts still appear. |
| `-v`, `--verbose` | Show the full OpenTofu output instead of a summary. |

---

### `client register`

Register this BYO box as a manual client and run the client container.

```bash
lablink client register --allocator-url URL --register-token TOKEN [OPTIONS]
```

Run this **on the machine you want to add to the pool**, not on the allocator host.
It registers the box with the allocator, writes the returned secrets to
`~/.lablink/client.env` (mode `0600`), and then `docker run`s the client container.

Auto-detects hostname, LAN IP, machine identity, and GPU presence/model; every one
of those can be overridden. If docker is missing, the env file is preserved so you
can install docker and re-run with `--force`.

The allocator's admin UI renders a ready-to-paste command for this at
**`/admin/byo-onboarding`**, with the flags already matched to your configured
connectivity mode.

| Option | Description |
|---|---|
| `--allocator-url URL` | Base URL of the allocator, e.g. `https://lablink.example.com`. **Required.** |
| `--register-token TOKEN` | The deployment's bootstrap register token, from the allocator operator. Prompted if omitted; also read from `$LABLINK_REGISTER_TOKEN`. **Required.** |
| `--hostname NAME` | Override the auto-detected hostname. |
| `--lan-ip IP` | Override the auto-detected LAN IP. |
| `--machine-identity ID` | Override the auto-detected machine identifier. |
| `--gpu-present` / `--no-gpu-present` | Override auto-detected GPU presence. |
| `--gpu-model STR` | Override the auto-detected GPU model string. |
| `--overlay-hostname NAME` | Register a **mesh-overlay** client under this Tailscale hostname (your choice). Requires `--tailscale-authkey`. |
| `--tailscale-authkey KEY` | Auth key the client will use to join the tailnet. Required with `--overlay-hostname`. |
| `--run-locally` / `--no-run-locally` | With `--overlay-hostname`: whether to `docker run` the client here now (default: on). `--no-run-locally` instead prints the secrets for pasting into a separate workload submission, and then also requires `--hostname` and `--machine-identity`. |
| `--tunnel` | Register a **reverse-tunnel** client: the box dials *out* to the allocator and holds one connection open, instead of the allocator dialling in. For networks that won't carry Tailscale and boxes that can't accept inbound connections. Takes no arguments — the allocator mints every value needed. |
| `--force` | Overwrite an existing `~/.lablink/client.env`. Mints a new client secret, orphaning any running container. |
| `--env-file PATH` | Where to write the secrets. Default `~/.lablink/client.env`. |
| `--insecure` | Skip TLS verification. Use when the allocator's `ssl.provider` is self-signed. |

The registration shape must match the allocator's configured
`manual.connectivity`, or the allocator rejects it with a 400:

| `manual.connectivity` | Register with |
|---|---|
| `lan_direct` | no connectivity flag |
| `mesh_overlay` | `--overlay-hostname` + `--tailscale-authkey` |
| `reverse_tunnel` | `--tunnel` |

---

### `client unregister`

Tear down a registered BYO box.

```bash
lablink client unregister [--env-file PATH] [--insecure] [--yes]
```

Best-effort notifies the allocator, then removes the `lablink-client` container and
deletes the env file. Idempotent — does nothing and exits 0 if there is no env
file. Safe to run after `lablink destroy`, when the allocator is expected to be
unreachable.

Deliberately **keeps** a mesh-overlay client's Tailscale node identity, so
re-registering lands back on the same tailnet node under the same name. Use
[`client reset-overlay`](#client-reset-overlay) when you want a fresh node.

| Option | Description |
|---|---|
| `--env-file PATH` | Path to `client.env`. Default `~/.lablink/client.env`. |
| `--insecure` | Skip TLS verification for the notify call. |
| `-y`, `--yes` | Skip the confirmation prompt. |

---

### `client reset-overlay`

Discard this box's persisted mesh-overlay node identity.

```bash
lablink client reset-overlay [--yes]
```

Only relevant to a mesh-overlay client. Run it when you want the next
`client register` to join the tailnet as a brand-new node rather than reusing the
existing one.

!!! warning "This does not delete the old machine from your tailnet"
    The previous node goes offline still holding its name, so the new node is given
    a numeric suffix (`-1`, `-2`, …) until you delete the stale machine in the
    Tailscale admin console.

Requires the `lablink-client` container to be gone already — docker will not remove
an attached volume.

| Option | Description |
|---|---|
| `-y`, `--yes` | Skip the confirmation prompt. |

---

### `client doctor`

Check this machine's BYO client.

```bash
lablink client doctor
```

Run it **on a client box**, not on the allocator host. Three checks:

| Check | Passes when |
|---|---|
| Registered | `~/.lablink/client.env` exists and carries this box's credentials |
| Container | the `lablink-client` container exists and is running |
| Log shipper | the in-container shipper is alive and forwarding to the allocator |

Most failures are fixed by re-running [`client register`](#client-register).

Distinct from the top-level [`doctor`](#doctor), which checks *operator-side*
prerequisites before a deploy (docker under the manual provider; OpenTofu, AWS
credentials, S3 and AMI under the AWS provider).

---

## Operations commands

### `status`

Show deployment health and inventory.

```bash
lablink status [--config PATH]
```

**AWS provider** shows four sections:

1. **OpenTofu State** — outputs like `ec2_public_ip`, `ec2_public_dns`, DNS/ALB records.
2. **Health Checks** — DNS resolution, allocator `/api/health`, SSL cert expiry (if HTTPS is enabled).
3. **Client VMs** — per-VM state and current hourly burn rate.
4. **Cost Estimate** — daily and monthly dollar estimates, pulled from the AWS Pricing API with a fallback table.

If your AWS credentials are missing or expired, an **AWS credentials** section is
printed first with the reason and how to authenticate. The OpenTofu state and
Client VM sections then say they're unavailable rather than showing an empty
result, and costs fall back to the built-in price table.

If the credentials are valid but lack a required IAM permission — or any other AWS
error occurs — the affected section reports that error in place, with guidance to
fix the policy rather than to re-authenticate.

**Manual provider** shows the docker-compose container status and the allocator's
HTTP health endpoint. There is no cost estimate — the hardware is yours.

| Option | Description |
|---|---|
| `-c`, `--config PATH` | Path to `config.yaml`. |

---

### `logs`

View allocator and client logs.

```bash
lablink logs [--config PATH]
```

**AWS provider:** opens a Textual-based viewer that streams cloud-init and
container logs from the allocator and any running client VMs. Logs auto-fetch
every 5 seconds for the selected VM; the status bar shows the last fetch time and
the current cadence. Use `a` to toggle auto-fetch off (and back on), `r` to fetch
once now, `1`/`2` to switch between the cloud-init and container tabs, and `q` to
quit.

The view only repaints when the logs actually changed, so scrolling back through
an error is not interrupted by a tick that found nothing new. Each tick is armed
only after the previous fetch finishes, so a slow allocator SSH round-trip
stretches the cadence instead of stacking up connections.

**Manual provider:** tails the local `lablink-allocator` container's logs. Per-VM
client logs are not centralized in this mode — run `docker logs lablink-client` on
each BYO box.

| Option | Description |
|---|---|
| `-c`, `--config PATH` | Path to `config.yaml`. |

---

### `export-metrics`

Export deployment metrics to CSV or JSON.

```bash
lablink export-metrics [--client] [--allocator] [--format FMT] [--output PATH] [--include-logs] [--config PATH]
```

Writes metrics to disk for offline analysis. Two data sources:

- `--client` — per-VM metrics from the allocator's API (requires the allocator to be running).
- `--allocator` — per-deploy metrics from the local cache at `~/.lablink/deployments/` (works after `lablink destroy`).

With no source flag, both are exported and `_client` / `_allocator` suffixes are
appended to the base output name.

Allocator metrics are scoped to the config's `deployment_name` **and** provider —
the cache holds a record per deploy attempt for every deployment on the machine,
and a name reused across providers has records of two different shapes in it. AWS
deploys populate the `allocator_terraform_*` columns; manual (compose) deploys
populate `allocator_compose_up_duration_seconds` instead. Both populate
`allocator_health_check_duration_seconds` and the total.

| Option | Description |
|---|---|
| `--client` | Export per-VM client metrics from the allocator. |
| `--allocator` | Export per-deploy allocator metrics from the local cache, scoped to this config's deployment and provider. Skips the network. |
| `-f`, `--format FMT` | `csv` (default) or `json`. |
| `-o`, `--output PATH` | Output file path. With a single source flag it is the literal path; with both (or neither), it is a base name and `_client` / `_allocator` suffixes are added before the extension. Default: `metrics_client.<fmt>` and/or `metrics_allocator.<fmt>`. |
| `--include-logs` | Include `cloud_init_logs` and `docker_logs` columns. Large — opt-in only. |
| `-c`, `--config PATH` | Path to `config.yaml`. With only `--allocator`, it is loaded when present (to scope the export) but not required — the command still works on a machine that has no config, exporting the whole cache. |

---

### `stats`

Show a cohort session-metrics summary in the terminal.

```bash
lablink stats [--config PATH]
```

Prints the same cohort summary the admin UI shows under **Session Metrics** —
participation funnel and aggregate time-in-software figures. It reads the
allocator's `/api/session-metrics/summary` endpoint, the same view model the web UI
consumes, so the two can never disagree. Needs a reachable allocator and admin
credentials; the figures only populate for deployments running with
`monitoring.enabled: true` (see
[Monitoring Options](../configuration.md#monitoring-options-monitoring)).

For the underlying rows rather than the summary, use
[`export-metrics --client`](#export-metrics).

| Option | Description |
|---|---|
| `-c`, `--config PATH` | Path to `config.yaml`. |

---

## Maintenance commands

### `show-config`

View the current LabLink configuration.

```bash
lablink show-config [--config PATH]
```

Pretty-prints the YAML with syntax highlighting and runs schema validation. Reports
validation errors inline.

| Option | Description |
|---|---|
| `-c`, `--config PATH` | Path to `config.yaml`. |

---

### `cleanup`

Remove deployment resources and local state.

```bash
lablink cleanup [--dry-run] [--config PATH]
```

**AWS provider:** deletes orphaned EC2/IAM/EIP/security-group resources tagged with
your deployment name — the kind of leftovers a failed or interrupted `destroy`
leaves behind — plus the environment-specific OpenTofu state files.

**Manual provider:** runs `docker compose down --volumes` on the local stack and
removes the compose working directory.

| Option | Description |
|---|---|
| `--dry-run` | Show what would be deleted without making changes. **AWS provider only** — the manual provider's cleanup is non-destructive until you confirm. |
| `-c`, `--config PATH` | Path to `config.yaml`. |

---

### `cache-clear`

Clear LabLink caches.

```bash
lablink cache-clear [--deployments] [--all] [--stale]
```

By default clears the OpenTofu template cache at `~/.lablink/cache/terraform/`.
With `--deployments`, clears the deployment metrics cache at
`~/.lablink/deployments/` instead. With `--all`, clears both.

| Option | Description |
|---|---|
| `--deployments` | Clear the deployment metrics cache instead of the OpenTofu template cache. |
| `--all` | Clear all LabLink caches (OpenTofu templates and deployment metrics). |
| `--stale` | With `--deployments`, delete only `in_progress` records (leftovers from plan-cancel or Ctrl-C). Ignored without `--deployments`. |

---

## Getting help at the command line

For the authoritative, always-current help text, use:

```bash
lablink --help              # top-level: lists all commands
lablink <command> --help    # per-command: lists all flags
lablink client --help       # the client-fleet subcommand group
```
