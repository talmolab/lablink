# CLI Reference

Complete reference for every `lablink` command. Grouped to match the `lablink --help` output.

!!! note "Manual reference"
    This page is hand-written from `packages/cli/src/lablink_cli/app.py`. For the authoritative help text, run `lablink <command> --help`. Auto-generated reference is planned once the package is published to PyPI.

## Global options

Every subcommand accepts `--config` to override the default config path:

```bash
lablink <command> --config /path/to/config.yaml
```

Default: `~/.lablink/config.yaml`. If the file is missing, the command exits with a hint to run `lablink configure`.

---

## Setup commands

### `configure`

Create or edit the LabLink configuration.

```bash
lablink configure [--config PATH]
```

Launches a TUI wizard that generates or edits `config.yaml`, then automatically runs [`setup`](#setup) to create the AWS resources Terraform needs for remote state (S3 bucket + DynamoDB lock table).

| Option | Description |
|---|---|
| `-c`, `--config PATH` | Path to `config.yaml`. Default: `~/.lablink/config.yaml`. |

---

### `setup`

Create S3 + DynamoDB for remote Terraform state.

```bash
lablink setup [--config PATH]
```

Automatically run during [`configure`](#configure). Use this command on its own to recreate state resources if they were deleted out of band.

| Option | Description |
|---|---|
| `-c`, `--config PATH` | Path to `config.yaml`. |

---

### `doctor`

Check prerequisites and configuration.

```bash
lablink doctor
```

Runs six pre-flight checks: Terraform installed, config file exists, config validates, AWS credentials, S3 state bucket exists, AMI known for the configured region. Exit code is non-zero if any check fails.

Takes no options.

---

## Deployment

### `deploy`

Deploy LabLink infrastructure with Terraform.

```bash
lablink deploy [--config PATH] [--template-version V] [--terraform-bundle PATH] [--yes]
```

Downloads the pinned `lablink-template` Terraform files (or uses a cached / bundled copy), renders your config into Terraform variables, and runs `terraform apply`. Prompts once for admin and database passwords — these are **not** stored in `config.yaml`.

| Option | Description |
|---|---|
| `-c`, `--config PATH` | Path to `config.yaml`. |
| `--template-version V` | Override the pinned template version (e.g. `v0.2.0`). Skips checksum verification. |
| `--terraform-bundle PATH` | Path to a local template tarball for offline deploys. |
| `-y`, `--yes` | Skip confirmation prompts. Does not bypass credential prompts (admin/db passwords are still required). |

---

### `destroy`

Tear down LabLink infrastructure.

```bash
lablink destroy [--config PATH] [--yes]
```

Runs `terraform destroy` against the deployment's working directory. Removes the allocator EC2 instance, security groups, key pair, and any ALB/Route 53 records Terraform owns. Client VMs owned by the allocator are destroyed along with it.

The S3 state bucket and DynamoDB lock table are **not** removed — reuse them on the next deploy, or tear them down with [`cleanup`](#cleanup).

| Option | Description |
|---|---|
| `-c`, `--config PATH` | Path to `config.yaml`. |
| `-y`, `--yes` | Skip confirmation prompts. Password prompts still appear. |

---

### `launch-client`

Launch client VMs via the allocator service.

```bash
lablink launch-client --num-vms N [--config PATH]
```

Calls the allocator's create-VM endpoint. The allocator provisions the VMs in its own Terraform workspace — the CLI only speaks to its HTTP API here. Terraform is not required locally for this command.

| Option | Description |
|---|---|
| `-n`, `--num-vms N` | Number of client VMs to launch. **Required.** |
| `-c`, `--config PATH` | Path to `config.yaml`. |

---

## Operations

### `status`

Health checks, Terraform state, and cost estimate.

```bash
lablink status [--config PATH]
```

Shows four sections:

1. **Terraform State** — outputs like `ec2_public_ip`, `ec2_public_dns`, DNS/ALB records.
2. **Health Checks** — DNS resolution, allocator `/api/health`, SSL cert expiry (if HTTPS is enabled).
3. **Client VMs** — per-VM state and current hourly burn rate.
4. **Cost Estimate** — daily and monthly dollar estimates, pulled from the AWS Pricing API with a fallback table.

| Option | Description |
|---|---|
| `-c`, `--config PATH` | Path to `config.yaml`. |

---

### `logs`

View VM logs in an interactive TUI.

```bash
lablink logs [--config PATH]
```

Opens a Textual-based viewer that streams cloud-init and container logs from the allocator and any running client VMs.

| Option | Description |
|---|---|
| `-c`, `--config PATH` | Path to `config.yaml`. |

Use `q` to quit, `/` to search, `n`/`N` for next/previous match.

---

### `export-metrics`

Export deployment metrics to CSV or JSON.

```bash
lablink export-metrics [--client] [--allocator] [--format FMT] [--output PATH] [--include-logs] [--config PATH]
```

Writes metrics to disk for offline analysis. Two data sources:

- `--client` — per-VM metrics from the allocator's API (requires the allocator to be running).
- `--allocator` — per-deploy metrics from the local cache at `~/.lablink/deployments/` (works after `lablink destroy`).

With no source flag, both are exported and `_client` / `_allocator` suffixes are appended to the base output name.

| Option | Description |
|---|---|
| `--client` | Export per-VM client metrics from the allocator. |
| `--allocator` | Export per-deploy allocator metrics from the local cache. Skips the network. |
| `-f`, `--format FMT` | `csv` (default) or `json`. |
| `-o`, `--output PATH` | Output file path. With both sources, treated as a base name; `_client` / `_allocator` suffixes are added. Default: `metrics_client.<fmt>` and/or `metrics_allocator.<fmt>`. |
| `--include-logs` | Include `cloud_init_logs` and `docker_logs` columns. |
| `-c`, `--config PATH` | Path to `config.yaml`. Skipped when only `--allocator` is passed. |

---

## Maintenance

### `show-config`

View the current LabLink configuration.

```bash
lablink show-config [--config PATH]
```

Pretty-prints the YAML with syntax highlighting and runs schema validation. Reports validation errors inline.

| Option | Description |
|---|---|
| `-c`, `--config PATH` | Path to `config.yaml`. |

---

### `cleanup`

Clean up orphaned AWS resources and local state.

```bash
lablink cleanup [--dry-run] [--config PATH]
```

Finds resources tagged with your deployment name that were left behind by a failed or interrupted `destroy` and removes them.

| Option | Description |
|---|---|
| `--dry-run` | Show what would be deleted without making changes. |
| `-c`, `--config PATH` | Path to `config.yaml`. |

---

### `cache-clear`

Clear LabLink caches.

```bash
lablink cache-clear [--deployments] [--all] [--stale]
```

By default clears the Terraform template cache at `~/.lablink/cache/terraform/`. With `--deployments`, clears the deployment metrics cache at `~/.lablink/deployments/` instead. With `--all`, clears both.

| Option | Description |
|---|---|
| `--deployments` | Clear the deployment metrics cache instead of the Terraform template cache. |
| `--all` | Clear all LabLink caches (Terraform templates and deployment metrics). |
| `--stale` | With `--deployments`, delete only `in_progress` records (leftovers from plan-cancel or Ctrl-C). Ignored without `--deployments`. |

---

## Getting help at the command line

For the authoritative, always-current help text, use:

```bash
lablink --help              # top-level: lists all commands
lablink <command> --help    # per-command: lists all flags
```
