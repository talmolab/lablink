# Quickstart

LabLink deploys three ways. The two AWS paths produce the same allocator
infrastructure and store OpenTofu state in S3; they differ in where OpenTofu
runs. The third skips AWS entirely.

Start with the CLI for the shortest AWS setup. Use the template repository when
you want to own its OpenTofu files and GitHub Actions workflows. The manual
provider uses the same config schema without AWS.

!!! tip "No AWS account?"
    Set `provider: manual` and the allocator runs as a local docker-compose stack, with client machines you register yourself. No AWS account, no OpenTofu, no cloud bill — see [Bring-Your-Own Clients](cli/byo-clients.md).

<div class="grid cards" markdown>

- :material-console: **Quickstart: CLI**

    ---

    Install the `lablink` CLI and run `lablink configure && lablink deploy` from your own machine. A single `config.yaml` drives everything; OpenTofu templates are pulled from a pinned release under the hood.

    Best when you want a **standard deployment without maintaining a repo** — one config file, no Dockerfile or `.tf` to edit.

    [:octicons-arrow-right-24: Quickstart: CLI](cli/first-deployment.md)

- :material-source-branch: **Quickstart: Template repo**

    ---

    Create a repository from [lablink-template](https://github.com/talmolab/lablink-template). You own its OpenTofu `.tf` files, configuration, and GitHub Actions workflows; deploys run through CI.

    Best when you need to **customize** infrastructure resources or workflow steps. A custom Docker image and client AMI can also be selected in the CLI's config.

    [:octicons-arrow-right-24: Quickstart: Template repo](quickstart-template.md)

</div>

For a detailed path comparison, see the [CLI overview](cli/index.md).

## Prerequisites

The requirements differ by path. See [Prerequisites](prerequisites.md) before
installing tools.

## Next steps

- [:material-source-branch: Quickstart: Template repo](quickstart-template.md)
- [:material-console: Quickstart: CLI](cli/first-deployment.md)
- [:material-server-network: Bring-Your-Own Clients](cli/byo-clients.md) — the manual provider, no AWS.
- [CLI Overview](cli/index.md) — deeper comparison of the paths.
