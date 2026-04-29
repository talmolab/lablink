# Installing the CLI

The `lablink` command is distributed with the [LabLink repository](https://github.com/talmolab/lablink) as one of three packages in a `uv` workspace (`packages/allocator`, `packages/client`, `packages/cli`). Until the CLI is published to PyPI, install it from source with `uv sync --all-packages`.

!!! note "PyPI coming soon"
    Once published, `uv tool install lablink` (or `pip install lablink`) will be the recommended install. For now, use the workspace install below.

## Prerequisites

Before installing, make sure you have:

- **[uv](https://docs.astral.sh/uv/)** — the Python project manager used by this repo. Install with `curl -LsSf https://astral.sh/uv/install.sh | sh` or see the [official install guide](https://docs.astral.sh/uv/getting-started/installation/).
- **Python 3.10+** — uv can manage this for you (`uv python install 3.11`). Check with `python --version`.
- **Terraform 1.6+** — the CLI drives Terraform under the hood. Install from [developer.hashicorp.com/terraform/install](https://developer.hashicorp.com/terraform/install).
- **AWS credentials** configured locally (either `aws configure` or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` environment variables). See [Prerequisites](../prerequisites.md#configure-aws-credentials).
- **An AWS account** with permissions to create EC2, S3, DynamoDB, IAM, and (optionally) Route 53 resources. See [AWS Setup (Manual)](../aws-setup.md) for the full permission list.

## Install from source

Clone the repo and run `uv sync --all-packages` at the root. This installs all three workspace packages (allocator, client, CLI) as editable — the CLI depends on `lablink-allocator-service`, which uv resolves from the workspace automatically.

```bash
git clone https://github.com/talmolab/lablink.git
cd lablink
uv sync --all-packages
```

uv creates `.venv/` on first sync. Run the CLI either directly through uv:

```bash
uv run lablink --help
```

…or by activating the venv:

```bash
source .venv/bin/activate
lablink --help
```

You should see the grouped command list (Setup, Deployment, Operations, Maintenance) — the same panels Typer prints for `--help`.

!!! tip "Running from outside the repo"
    If you want `lablink` available from any directory, activate `.venv` in your shell profile, or install via `uv tool install --from ./packages/cli lablink-cli` (note: this will fail today because the CLI's workspace dep on `lablink-allocator-service` isn't yet resolvable outside the workspace — revisit after PyPI publish).

## Verify the installation

Once installed, run `lablink` with no arguments to confirm everything is wired up:

```bash
uv run lablink
```

On a fresh install (no config yet), you'll see a **Getting started** panel pointing at the next three commands:

```text
╭─ Getting started ──────────────────────────────────────╮
│ Welcome to LabLink. First-time setup:                  │
│                                                        │
│   1. lablink configure   create config + AWS state…    │
│   2. lablink doctor      verify prerequisites          │
│   3. lablink deploy      deploy the allocator          │
│                                                        │
│ For the full command list, run 'lablink --help'.       │
╰────────────────────────────────────────────────────────╯
```

If you instead see the full command list (Setup / Deployment / Operations / Maintenance panels), it means `~/.lablink/config.yaml` already exists from a previous run — that's fine, skip ahead to [Step 1: Configure](first-deployment.md#step-1-configure).

## Check your environment

Run `lablink doctor` to validate prerequisites end-to-end:

```bash
uv run lablink doctor
```

It checks:

| Check | What it verifies |
|---|---|
| Terraform installed | `terraform` is on PATH and reports a version |
| Config file | `~/.lablink/config.yaml` exists |
| Config validates | The config parses and passes schema validation |
| AWS credentials | `sts:GetCallerIdentity` succeeds for the configured region |
| S3 state bucket | The `bucket_name` in your config actually exists |
| AMI for region | The CLI knows an AMI for `cfg.app.region` |

A fresh install (before `lablink configure`) will fail on "Config file" and anything that depends on it. That's expected — move on to [First Deployment](first-deployment.md).

## Where things live

The CLI stores state under `~/.lablink/`:

| Path | Purpose |
|---|---|
| `~/.lablink/config.yaml` | Default config file written by `lablink configure` |
| `~/.lablink/cache/terraform/<version>/` | Cached Terraform templates downloaded from the `lablink-template` repo |
| `~/.lablink/deployments/` | Per-deploy metrics records (readable by `lablink export-metrics --allocator`) |
| `~/.lablink/deploys/<name>/` | Working directory Terraform runs in for each deployment |

Pass `--config /path/to/config.yaml` to any command to use a different config file.

## Upgrading

Pull the latest source and re-sync:

```bash
cd lablink
git pull
uv sync --all-packages
```

!!! note "Template version"
    The CLI pins a specific version of the `lablink-template` Terraform files. After upgrading the CLI, the first `lablink deploy` will download the new template version into `~/.lablink/cache/terraform/`.

## Next steps

- [Run your first deployment](first-deployment.md)
- [Day-to-day operations](managing-deployments.md)
- Full command reference: [CLI Reference](../reference/cli.md)
