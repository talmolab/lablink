# Installing the CLI

The `lablink` command is published to PyPI as [`lablink-cli`](https://pypi.org/project/lablink-cli/). Install it as a standalone tool to deploy and manage LabLink, or [from source](#install-from-source) if you intend to work on the CLI itself — it is also one of three packages in this repo's `uv` workspace (`packages/allocator`, `packages/client`, `packages/cli`).

!!! note "The package and the command have different names"
    The PyPI package is **`lablink-cli`**; the command it installs is **`lablink`**. There is no `lablink` package on PyPI, so `pip install lablink` will fail.

!!! warning "Pre-release"
    The published version is a pre-release (`0.1.0a1`). Expect rough edges, and pin an exact version (`lablink-cli==0.1.0a1`) if you need a reproducible install.

## Prerequisites

Before installing, make sure you have:

- **[uv](https://docs.astral.sh/uv/)** — the Python project manager used by this repo. Install with `curl -LsSf https://astral.sh/uv/install.sh | sh` or see the [official install guide](https://docs.astral.sh/uv/getting-started/installation/).
- **Python 3.10+** — uv can manage this for you (`uv python install 3.11`). Check with `python --version`.

The rest depends on which provider you deploy with.

=== "`provider: aws`"
    - **OpenTofu 1.10+** — the CLI drives OpenTofu under the hood. Install from [opentofu.org/docs/intro/install](https://opentofu.org/docs/intro/install/). Older releases vendor an `aws-sdk-go-v2` that can corrupt S3 state on an upload retry, so `lablink doctor` rejects them.
    - **AWS credentials** configured locally (either `aws configure` or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` environment variables). See [Prerequisites](../prerequisites.md#configure-aws-credentials).
    - **An AWS account** with permissions to create EC2, S3, DynamoDB, IAM, and (optionally) Route 53 resources. See [AWS Setup (Manual)](../aws-setup.md) for the full permission list.

=== "`provider: manual`"
    - **Docker** and the **`docker compose` v2 plugin**, on the allocator host and on every client box. The allocator runs as a compose stack and each client runs the client container.
    - No AWS account, no AWS credentials, and no OpenTofu — see [Bring-Your-Own Clients](byo-clients.md).

## Install from PyPI

This is the path for using the CLI. Install it as a standalone tool:

```bash
uv tool install lablink-cli
```

That puts `lablink` on your `PATH` in its own isolated environment, which is what you want for a command-line tool — it cannot collide with another project's dependencies. Verify it:

```bash
lablink --version
```

`pip install lablink-cli` works too, into whichever environment is currently active. No `--pre` flag is needed despite the alpha version: it is the only release right now, so both installers select it. Once a stable release exists, plain installs will prefer that instead, and you would need `--pre` to keep getting alphas.

## Install from source

Use this if you intend to modify the CLI. Clone the repo and run `uv sync --all-packages` at the root. This installs all three workspace packages (allocator, client, CLI) as editable — the CLI depends on `lablink-allocator-service`, which uv resolves from the workspace automatically.

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
lablink
```

If you installed from source rather than PyPI, use `uv run lablink` instead, or activate the venv first.

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
| OpenTofu installed | `tofu` is on PATH and reports a version |
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
| `~/.lablink/cache/terraform/<version>/` | Cached OpenTofu templates downloaded from the `lablink-template` repo |
| `~/.lablink/deployments/` | Per-deploy metrics records (readable by `lablink export-metrics --allocator`) |
| `~/.lablink/deploy/<name>/<environment>/` | Working directory OpenTofu runs in for each deployment |

Pass `--config /path/to/config.yaml` to any command to use a different config file.

## Upgrading

If you installed from PyPI:

```bash
uv tool upgrade lablink-cli   # or: pip install --upgrade lablink-cli
```

If you installed from source, pull and re-sync:

```bash
cd lablink
git pull
uv sync --all-packages
```

!!! note "Template version"
    The CLI pins a specific version of the `lablink-template` OpenTofu files. After upgrading the CLI, the first `lablink deploy` will download the new template version into `~/.lablink/cache/terraform/`.

## Uninstall

!!! warning "Destroy your deployments first"
    Uninstalling the CLI does **not** stop AWS charges. Everything `lablink
    deploy` created keeps running and billing, and the CLI is the only thing
    that knows how to tear it down. Run this *before* removing anything:

    ```bash
    lablink destroy
    ```

### 1. Clear out AWS

`lablink destroy` removes what OpenTofu owns. Two things deliberately outlive it:

- **Orphaned resources** left by an interrupted deploy. `lablink cleanup --dry-run` lists them; `lablink cleanup` deletes them.
- **The S3 state bucket and DynamoDB lock table**, kept so the next deploy can reuse them (~$0.05/month). To remove those too, see [Cleanup orphaned resources](managing-deployments.md#cleanup-orphaned-resources).

Confirm nothing is left before moving on:

```bash
lablink status
```

### 2. Remove the CLI

If you installed from PyPI:

```bash
uv tool uninstall lablink-cli   # or: pip uninstall lablink-cli
```

If you installed from source, delete the checkout (the venv lives inside it):

```bash
rm -rf /path/to/lablink
```

### 3. Remove local state

The CLI never cleans up `~/.lablink/` on its own:

```bash
rm -rf ~/.lablink
```

This is local-only — it touches nothing in AWS. What you lose:

| Path | Consequence |
|---|---|
| `config.yaml` | Re-run `lablink configure` to recreate it |
| `cache/terraform/` | Re-downloaded on the next deploy |
| `deployments/` | Per-deploy metrics history is gone; export it first with `lablink export-metrics` if you want to keep it |
| `deploy/` | OpenTofu working directories. **Delete these only after `lablink destroy` succeeds** — losing them while resources still exist orphans them from local state |

!!! tip "Keeping the config"
    To reinstall later against the same deployment, keep `~/.lablink/config.yaml` and delete the rest.

## Next steps

- [Run your first deployment](first-deployment.md)
- [Day-to-day operations](managing-deployments.md)
- Full command reference: [CLI Reference](../reference/cli.md)
