# Managing Deployments

Day-to-day operations once an allocator is running: add client machines, follow logs, export metrics, and clean up.

Every command on this page reads `~/.lablink/config.yaml` by default. Pass `--config /path/to/other.yaml` to target a different deployment.

!!! note "Provider-dependent behavior"
    Most of these commands branch on your config's `provider`. The AWS behavior is
    described below, with the manual-provider difference called out where there is
    one. For the full bring-your-own workflow in one place, see
    [Bring-Your-Own Clients](byo-clients.md).

## Add client machines

**AWS provider** — ask the allocator to provision VMs:

```bash
lablink client launch --num-vms 5
```

The allocator runs its own Terraform workspace inside the EC2 instance — the CLI only hits its HTTP API, so you don't need Terraform locally for this step.

| Flag | Description |
|---|---|
| `-n`, `--num-vms` | Number of client VMs to launch. Required. |
| `-c`, `--config` | Override the default config path. |
| `-v`, `--verbose` | Show the full Terraform output instead of a summary. |

Watch `lablink status` to see the VMs transition from pending → running.

**Manual provider** — run this *on each box you're adding*, not on the allocator host:

```bash
lablink client register --allocator-url http://192.168.1.42 --register-token <token>
```

`lablink client launch` no-ops under the manual provider. To remove a box later, run
`lablink client unregister` on it. Details and the mesh-overlay / reverse-tunnel
variants: [Bring-Your-Own Clients](byo-clients.md#step-4-register-each-box).

## Check status

```bash
lablink status
```

Shows Terraform outputs, health checks, per-VM state, and a cost estimate. This is the command to run when you want to know "is the allocator up and how much is this costing me?"

See [First Deployment](first-deployment.md#step-4-verify) for what each section means.

Under the manual provider it instead shows docker-compose container status and the
allocator's health endpoint — no cost estimate, since the hardware is yours.

## Follow logs

```bash
lablink logs
```

Opens an interactive TUI that streams logs from the allocator and any running client VMs. Select a VM in the left pane to follow its `cloud-init` and container logs in the right pane.

!!! tip "Quit and search"
    Use `q` to exit. The viewer supports `/` to search, `n` / `N` for next/previous match, and arrow keys for navigation.

Under the manual provider there's no TUI — it tails the local `lablink-allocator`
container. Per-VM client logs aren't centralized in that mode; run
`docker logs lablink-client` on the box itself.

## Export metrics

```bash
lablink export-metrics --format csv --output metrics.csv
```

Writes deployment metrics to disk for offline analysis. Two sources:

| Flag | Data | Requires allocator running? |
|---|---|---|
| `--client` | Per-VM metrics pulled from the allocator's API (boot time, health status, logs) | Yes |
| `--allocator` | Per-deploy metrics from the local cache at `~/.lablink/deployments/` (deploy duration, Terraform phase timings) | **No** — works after `lablink destroy` |
| *(no flag)* | Both | Yes |

Other flags:

| Flag | Description |
|---|---|
| `-f`, `--format` | `csv` (default) or `json`. |
| `-o`, `--output` | Output path. With both data sources selected, this is treated as a base name and `_client` / `_allocator` suffixes are added before the extension. |
| `--include-logs` | Include `cloud_init_logs` and `docker_logs` columns. Large — opt-in only. |

Example — only allocator metrics after tear-down:

```bash
lablink export-metrics --allocator --format json -o post-mortem.json
```

## Session metrics summary

```bash
lablink stats
```

Prints the cohort session-metrics summary — participation funnel and aggregate
time-in-software — in your terminal. It reads the allocator's
`/api/session-metrics/summary` endpoint, the same view model the admin UI's
**Session Metrics** page uses, so the two can't disagree.

The figures only populate for deployments running with `monitoring.enabled: true`.
Use `export-metrics --client` when you want the underlying per-VM rows instead of
the summary.

## Show the current config

```bash
lablink show-config
```

Pretty-prints `~/.lablink/config.yaml` with syntax highlighting and runs schema validation. Useful for spotting typos before a deploy.

## Destroy the deployment

```bash
lablink destroy
```

Runs `terraform destroy` against the deployment's working directory (`~/.lablink/deploys/<name>/`). Tears down the allocator EC2 instance, security groups, key pair, and any ALB/Route 53 records. Client VMs owned by the allocator are destroyed along with it.

| Flag | Description |
|---|---|
| `-y`, `--yes` | Skip the confirmation prompt. Password prompts still appear. |
| `-v`, `--verbose` | Show the full Terraform output instead of a summary. |
| `--keep-data` | **Manual provider only** — preserve the Postgres data volume instead of the default full wipe, so registration history and sessions survive the next deploy. Ignored for AWS. |

Under the manual provider this brings the compose stack down instead of running Terraform.

## Cleanup orphaned resources

If a destroy was interrupted — Ctrl-C, an AWS outage, a deleted workspace — leftover resources may stay behind. The cleanup command finds and removes them:

```bash
lablink cleanup --dry-run   # preview
lablink cleanup             # actually delete
```

On AWS it targets EC2/IAM/EIP/security-group resources tagged with your deployment name, plus the environment-specific Terraform state files. `--dry-run` prints what would be deleted without touching AWS.

Under the manual provider it runs `docker compose down --volumes` and removes the compose working directory. `--dry-run` is AWS-only — the manual path confirms interactively instead.

## Clear local caches

The CLI stores two caches you may want to clear occasionally:

```bash
# Clear the Terraform template cache (~/.lablink/cache/terraform/)
lablink cache-clear

# Clear the deployment metrics cache (~/.lablink/deployments/)
lablink cache-clear --deployments

# Clear both
lablink cache-clear --all

# Only prune in-progress records (leftovers from plan-cancel or Ctrl-C)
lablink cache-clear --deployments --stale
```

Clearing the Terraform template cache forces the next deploy to re-download templates. Clearing the deployments cache removes the per-deploy records that back `lablink export-metrics --allocator`.

## Switching between deployments

Keep multiple config files if you manage more than one deployment:

`--config` is a per-command option, not a root one — it goes *after* the command:

```bash
lablink deploy --config ~/configs/workshop.yaml
lablink status --config ~/configs/dev.yaml
```

Each deployment gets its own working directory under `~/.lablink/deploys/<name>/` keyed by the `deployment_name` field in its config.

## Next steps

- [CLI Reference](../reference/cli.md) — every command and flag in one page.
- [Bring-Your-Own Clients](byo-clients.md) — the manual-provider workflow end to end.
- [Troubleshooting](../troubleshooting.md) — general LabLink issues (not CLI-specific).
- [Configuration](../configuration.md) — full `config.yaml` schema reference.
