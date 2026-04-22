# LabLink CLI

The `lablink` command is a CLI-driven alternative to the [lablink-template](https://github.com/talmolab/lablink-template) repository. It deploys the same allocator infrastructure to AWS — cloud resources are identical either way — but drives Terraform from your own machine instead of GitHub Actions.

!!! note "Status: pre-PyPI"
    The CLI is not yet published to PyPI. For now, install it from source with `uv sync --all-packages` — see [Installation](installation.md). `uv tool install lablink` will be the path once the package is released.

## CLI vs. template repo

Both paths deploy the same allocator service and manage the same set of AWS resources. They differ in **where Terraform runs** and **where state lives**.

| | Template repo | CLI |
|---|---|---|
| Where Terraform runs | GitHub Actions | Your machine |
| Where state lives | Shared S3 (per-repo) | Local S3 bucket you own |
| How you trigger a deploy | Push to `main` / run workflow | `lablink deploy` |
| Secrets management | GitHub repository secrets | AWS credentials on your machine, passwords prompted |
| Who can deploy | Anyone with repo access | Whoever has the AWS creds locally |
| Best for | Workshops, shared environments, production | Solo development, pre-workshop iteration, local debugging |

## When to pick which

Pick the **CLI** when you want to:

- Stand a deployment up quickly from your laptop
- Iterate on configuration or Terraform changes without pushing commits
- Debug a failed deploy with direct access to Terraform output and logs
- Export metrics from a deployment that's already been torn down

Pick the **template repo** when you want to:

- Hand the deployment off to a team via GitHub permissions
- Run reproducible, audited deploys from CI
- Run workshops where multiple people may trigger deploys

You can also switch between them later — both read the same `config.yaml` schema.

## Next steps

1. [Install the CLI](installation.md)
2. [Run your first deployment](first-deployment.md)
3. [Manage an existing deployment](managing-deployments.md)
4. Full command reference: [CLI Reference](../reference/cli.md)
