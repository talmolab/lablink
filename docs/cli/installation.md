# Installing the CLI

The `lablink` command is distributed with the [LabLink repository](https://github.com/talmolab/lablink) under `packages/cli/`. Until it's published to PyPI, install it from source.

!!! note "PyPI coming soon"
    Once published, `pip install lablink` will be the recommended install. For now, use one of the methods below.

## Prerequisites

Before installing, make sure you have:

- **Python 3.10+** — check with `python --version`.
- **Terraform 1.6+** — the CLI drives Terraform under the hood. Install from [developer.hashicorp.com/terraform/install](https://developer.hashicorp.com/terraform/install).
- **AWS credentials** configured locally (either `aws configure` or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` environment variables). See [Prerequisites](../prerequisites.md#configure-aws-credentials).
- **An AWS account** with permissions to create EC2, S3, DynamoDB, IAM, and (optionally) Route 53 resources. See [AWS Setup (Manual)](../aws-setup.md) for the full permission list.

## Install from source

Clone the repo and install the CLI package in editable mode:

```bash
git clone https://github.com/talmolab/lablink.git
cd lablink
pip install -e packages/cli
```

!!! tip "Use a virtual environment"
    Install into a dedicated venv so the `lablink` command and its dependencies stay isolated:
    ```bash
    python -m venv .venv
    source .venv/bin/activate
    pip install -e packages/cli
    ```
    Or with `uv`:
    ```bash
    uv venv
    source .venv/bin/activate
    uv pip install -e packages/cli
    ```

Verify the install:

```bash
lablink --help
```

You should see the grouped command list (Setup, Deployment, Operations, Maintenance).

## Check your environment

Run `lablink doctor` to validate prerequisites end-to-end:

```bash
lablink doctor
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

Pull the latest source and reinstall:

```bash
cd lablink
git pull
pip install -e packages/cli --upgrade
```

!!! note "Template version"
    The CLI pins a specific version of the `lablink-template` Terraform files. After upgrading the CLI, the first `lablink deploy` will download the new template version into `~/.lablink/cache/terraform/`.

## Next steps

- [Run your first deployment](first-deployment.md)
- [Day-to-day operations](managing-deployments.md)
- Full command reference: [CLI Reference](../reference/cli.md)
