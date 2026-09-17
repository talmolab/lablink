# Managing Deployments

Day-to-day operations once an allocator is running: add client machines, follow logs, export metrics, and clean up.

Deployment commands read `~/.lablink/config.yaml` by default. Pass
`--config /path/to/other.yaml` on a command that accepts it to target another
deployment. `cache-clear` uses local cache paths and needs no deployment
config; `export-metrics --allocator` can run without one when exporting the
whole cache.

!!! note "This page describes the AWS provider"
    Most of these commands branch on your config's `provider`. Under
    `provider: manual` the same commands act on a local docker-compose stack
    instead — see [Bring-Your-Own Clients](byo-clients.md#day-to-day), which covers
    the manual workflow end to end.

## Launch client VMs

```bash
lablink client launch --num-vms 5
```

The allocator runs its own OpenTofu workspace inside the EC2 instance — the CLI only hits its HTTP API, so you don't need OpenTofu locally for this step.

Watch `lablink status` to see the EC2 instances transition to running.
See the [client launch reference](../reference/cli.md#client-launch) for flags.

Under the manual provider this no-ops; you add boxes with
[`lablink client register`](byo-clients.md#step-4-register-each-box) instead.

## Check status

```bash
lablink status
```

Shows the allocator URL, OpenTofu outputs, health checks, client inventory,
and daily cost estimate. See the [status reference](../reference/cli.md#status)
for each section.

## Follow logs

```bash
lablink logs
```

Opens an interactive TUI that streams logs from the allocator and any running client VMs. Select a VM in the left pane to follow its `cloud-init` and container logs in the right pane.

Use `q` to exit, `r` to refresh, `a` to toggle automatic fetching, and `1` /
`2` to select cloud-init or client-container logs.

## Export metrics

```bash
lablink export-metrics --format csv --output metrics.csv
```

Writes deployment metrics to disk for offline analysis. `--client` fetches
per-VM metrics from a running allocator; `--allocator` reads deploy timing
metrics from the local cache at `~/.lablink/deployments/` and works after
`lablink destroy`. With neither flag, it exports both.

Allocator metrics are **scoped to the deployment and provider in your config**.
The cache is shared by every deployment you have ever run, so an unscoped export
would put other deployments' rows in a file named after this one. Point
`--config` at a different config to export that deployment instead. On a machine
with no config at all, `--allocator` exports the whole cache and says how many
deployments it spans.

Reusing one `deployment_name` across providers is why the provider is part of the
scope: a name deployed first on AWS and later with `provider: manual` has records
of both shapes in the cache, and the OpenTofu phase columns say nothing about a
compose stack.

Example — only allocator metrics after tear-down:

```bash
lablink export-metrics --allocator --format json -o post-mortem.json
```

See the [export-metrics reference](../reference/cli.md#export-metrics) for
formats, output names, and log inclusion.

## Session metrics summary

```bash
lablink stats
```

Prints the cohort summary — participation funnel and aggregate time-in-software —
for deployments running with `monitoring.enabled: true`. See
[`stats`](../reference/cli.md#stats).

## Show the current config

```bash
lablink show-config
```

Pretty-prints `~/.lablink/config.yaml` with syntax highlighting and runs schema validation. Useful for spotting typos before a deploy.

## Destroy the deployment

```bash
lablink destroy
```

Runs `tofu destroy` against the deployment's working directory
(`~/.lablink/deploy/<name>/<environment>/`). Tears down the allocator EC2
instance, security groups, key pair, and any ALB/Route 53 records. Client VMs
owned by the allocator are destroyed along with it.

See the [destroy reference](../reference/cli.md#destroy) for confirmation,
verbosity, and the manual provider's `--keep-data` option.

## Cleanup orphaned resources

If a destroy was interrupted — Ctrl-C, an AWS outage, a deleted workspace — leftover resources may stay behind. The cleanup command finds and removes them:

```bash
lablink cleanup --dry-run   # preview
lablink cleanup             # actually delete
```

It targets tagged EC2/IAM/EIP/security-group resources, key pairs, and the
environment-specific OpenTofu state objects and lock entries. It leaves the
shared S3 bucket and DynamoDB table in place. `--dry-run` prints what would be
deleted without touching AWS.

## Clear local caches

The CLI stores two caches you may want to clear occasionally:

```bash
# Clear the OpenTofu template cache (~/.lablink/cache/terraform/)
lablink cache-clear

# Clear the deployment metrics cache (~/.lablink/deployments/)
lablink cache-clear --deployments

# Clear both
lablink cache-clear --all

# Only prune in-progress records (leftovers from plan-cancel or Ctrl-C)
lablink cache-clear --deployments --stale
```

Clearing the OpenTofu template cache forces the next deploy to re-download
templates. Clearing the deployments cache removes the per-deploy records
that back `lablink export-metrics --allocator`. See the
[cache-clear reference](../reference/cli.md#cache-clear) for all options.

## Switching between deployments

Keep multiple config files if you manage more than one deployment:

`--config` is a per-command option, not a root one — it goes *after* the command:

```bash
lablink deploy --config ~/configs/workshop.yaml
lablink status --config ~/configs/dev.yaml
```

Each deployment gets a working directory under
`~/.lablink/deploy/<name>/<environment>/`, keyed by the `deployment_name` and
`environment` fields in its config.

## Next steps

- [CLI Reference](../reference/cli.md) — every command and flag in one page.
- [Bring-Your-Own Clients](byo-clients.md) — the manual-provider workflow end to end.
- [Troubleshooting](../troubleshooting.md) — general LabLink issues (not CLI-specific).
- [Configuration](../configuration.md) — full `config.yaml` schema reference.
