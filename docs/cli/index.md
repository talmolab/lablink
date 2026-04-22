# LabLink CLI

The `lablink` command is a CLI-driven alternative to the [lablink-template](https://github.com/talmolab/lablink-template) repository. It deploys the same allocator infrastructure to AWS — cloud resources are identical either way — but drives Terraform from your own machine instead of GitHub Actions.

!!! note "Status: pre-PyPI"
    The CLI is not yet published to PyPI. For now, install it from source with `uv sync --all-packages` — see [Installation](installation.md). `uv tool install lablink` will be the path once the package is released.

## CLI vs. template repo

Both paths deploy the same allocator service and manage the same set of AWS resources. The practical difference is **how much of the deployment you own and configure yourself**.

| | Template repo | CLI |
|---|---|---|
| What you maintain | A full repo forked from `lablink-template` (Dockerfile, Terraform `.tf` files, GitHub Actions workflows, configs) | A single `config.yaml` |
| Customization surface | Every file in the repo — tweak AMIs, Docker images, Terraform resources, CI workflow, secrets | Whatever the `config.yaml` schema exposes (instance type, region, DNS, SSL, monitoring) |
| Where Terraform runs | GitHub Actions | Your machine |
| Where state lives | Shared S3 (per-repo) | Local S3 bucket you own |
| How you trigger a deploy | Push to `main` / run workflow | `lablink deploy` |
| Secrets management | GitHub repository secrets | AWS credentials on your machine, passwords prompted |
| Who can deploy | Anyone with repo access | Whoever has the AWS creds locally |
| Best for | Deployments you need to customize — bring-your-own Docker image, extra AWS resources, custom CI, bespoke workflow edits | Standard deployments where you just want it up — no repo to own, no workflow to maintain |

## When to pick which

Pick the **CLI** when you want to:

- Stand up a standard deployment without maintaining a fork of the template
- Keep the surface small — one config file, no Dockerfile or `.tf` edits
- Skip hopping between a GitHub repo, Actions logs, and local tooling
- Drive Terraform directly from your laptop and see its output inline

Pick the **template repo** when you want to:

- Bring your own Docker image, custom AMI baking, or your own entrypoint
- Add or modify AWS resources Terraform doesn't provision by default
- Customize the GitHub Actions workflow (extra steps, different triggers, etc.)
- Hand the deployment off to a team via GitHub permissions instead of sharing AWS credentials

You can switch between them later — both read the same `config.yaml` schema for the settings the CLI exposes.

## Next steps

1. [Install the CLI](installation.md)
2. [Run your first deployment](first-deployment.md)
3. [Manage an existing deployment](managing-deployments.md)
4. Full command reference: [CLI Reference](../reference/cli.md)
