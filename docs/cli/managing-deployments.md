# Managing Deployments

Day-to-day operations once an allocator is running: launch client VMs, follow logs, export metrics, and clean up.

Every command on this page reads `~/.lablink/config.yaml` by default. Pass `--config /path/to/other.yaml` to target a different deployment.

## Launch client VMs

```bash
lablink launch-client --num-vms 5
```

This asks the allocator to provision client VMs on your behalf. The allocator runs its own Terraform workspace inside the EC2 instance — the CLI only hits its HTTP API, so you don't need Terraform locally for this step.

| Flag | Description |
|---|---|
| `-n`, `--num-vms` | Number of client VMs to launch. Required. |
| `-c`, `--config` | Override the default config path. |

Watch `lablink status` to see the VMs transition from pending → running.

## Check status

```bash
lablink status
```

Shows Terraform outputs, health checks, per-VM state, and a cost estimate. This is the command to run when you want to know "is the allocator up and how much is this costing me?"

See [First Deployment](first-deployment.md#step-4-verify) for what each section means.

## Follow logs

```bash
lablink logs
```

Opens an interactive TUI that streams logs from the allocator and any running client VMs. Select a VM in the left pane to follow its `cloud-init` and container logs in the right pane.

!!! tip "Quit and search"
    Use `q` to exit. The viewer supports `/` to search, `n` / `N` for next/previous match, and arrow keys for navigation.

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

Pass `-y` / `--yes` to skip the confirmation prompt. Password prompts still appear.

## Cleanup orphaned resources

If a destroy was interrupted — Ctrl-C, an AWS outage, a deleted workspace — leftover resources may stay behind. The cleanup command finds and removes them:

```bash
lablink cleanup --dry-run   # preview
lablink cleanup             # actually delete
```

It targets resources tagged with your deployment name. `--dry-run` prints what would be deleted without touching AWS.

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

```bash
lablink --config ~/configs/workshop.yaml deploy
lablink --config ~/configs/dev.yaml status
```

Each deployment gets its own working directory under `~/.lablink/deploys/<name>/` keyed by the `deployment_name` field in its config.

## Next steps

- [CLI Reference](../reference/cli.md) — every command and flag in one page.
- [Troubleshooting](../troubleshooting.md) — general LabLink issues (not CLI-specific).
- [Configuration](../configuration.md) — full `config.yaml` schema reference.
