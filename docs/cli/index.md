# LabLink CLI

The `lablink` command is a CLI-driven alternative to the [lablink-template](https://github.com/talmolab/lablink-template) repository. It deploys the same allocator infrastructure to AWS — cloud resources are identical either way — but drives OpenTofu from your own machine instead of GitHub Actions.

!!! note "Installing"
    The CLI is on PyPI as [`lablink-cli`](https://pypi.org/project/lablink-cli/). Install it with `uv tool install lablink-cli` (or `pip install lablink-cli`) — see [Installation](installation.md).

    Note the package is `lablink-cli` while the command it installs is `lablink`.

## Two providers

The CLI can deploy in either of two modes, selected by the `provider` field in your
config:

| `provider` | Allocator runs on | Client machines | Needs AWS? |
|---|---|---|---|
| `aws` (default) | EC2, provisioned by OpenTofu | `lablink client launch` provisions them for you | Yes |
| `manual` | docker-compose, on a machine you already have | you register your own boxes with `lablink client register` | No |

Everything below compares the **AWS** path against the template repo. If you'd
rather run LabLink on hardware you already own — lab workstations, an on-prem
server, a scheduler-hosted workload — see
[Bring-Your-Own Clients](byo-clients.md) instead.

## CLI vs. template repo

Both paths deploy the same allocator service and manage the same set of AWS resources. The practical difference is **how much of the deployment you own and configure yourself**.

| | Template repo | CLI |
|---|---|---|
| What you maintain | A full repo forked from `lablink-template` (OpenTofu `.tf` files, GitHub Actions workflows, configs) | A single `config.yaml` |
| Customization surface | OpenTofu resources, CI workflow, and config values | Whatever the `config.yaml` schema exposes, including instance type, images, region, DNS, and SSL |
| Where OpenTofu runs | GitHub Actions | Your machine |
| Where state lives | S3 backend in your AWS account | S3 backend in your AWS account |
| How you trigger a deploy | Push to `test` or run the deployment workflow | `lablink deploy` |
| Secrets management | GitHub repository secrets | AWS credentials on your machine, passwords prompted |
| Who can deploy | Anyone with repo access | Whoever has the AWS creds locally |
| Best for | Custom AWS resources or CI workflows | Standard deployments without a repository to maintain |

Both paths let you select a custom client Docker image or AMI through
`config.yaml`. You can switch paths later because they use the same config
schema for those settings.

## Next steps

1. [Install the CLI](installation.md)
2. [Run your first deployment](first-deployment.md) (AWS) — or [bring your own clients](byo-clients.md) (no AWS)
3. [Manage an existing deployment](managing-deployments.md)
4. Full command reference: [CLI Reference](../reference/cli.md)
