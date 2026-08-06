# Quickstart

LabLink deploys three ways. Two of them produce the same allocator infrastructure on AWS and differ only in **where Terraform runs** and **where state lives**. The third skips AWS entirely.

Pick whichever fits your setup. You can switch between them later; all three read the same `config.yaml` schema.

!!! tip "No AWS account?"
    Set `provider: manual` and the allocator runs as a local docker-compose stack, with client machines you register yourself. No AWS account, no Terraform, no cloud bill — see [Bring-Your-Own Clients](cli/byo-clients.md).

<div class="grid cards" markdown>

- :material-source-branch: **Quickstart: Template repo**

    ---

    Create a repository from [lablink-template](https://github.com/talmolab/lablink-template). You own the full repo — Dockerfile, Terraform `.tf` files, GitHub Actions workflows — and deploys run through CI.

    Best when you need to **customize** the deployment: bring-your-own Docker image, custom AMI, extra AWS resources, or bespoke workflow edits.

    [:octicons-arrow-right-24: Quickstart: Template repo](quickstart-template.md)

- :material-console: **Quickstart: CLI**

    ---

    Install the `lablink` CLI and run `lablink configure && lablink deploy` from your own machine. A single `config.yaml` drives everything; Terraform templates are pulled from a pinned release under the hood.

    Best when you want a **standard deployment without maintaining a repo** — one config file, no Dockerfile or `.tf` to edit.

    [:octicons-arrow-right-24: Quickstart: CLI](cli/first-deployment.md)

</div>

## Which path should I pick?

| If you want to… | Use |
|---|---|
| Use your own Docker image or custom AMI | Template repo |
| Add or modify AWS resources Terraform doesn't provision by default | Template repo |
| Customize the GitHub Actions workflow | Template repo |
| Hand the deployment off to a team via GitHub permissions | Template repo |
| Stand up a standard deployment without forking the template | CLI |
| Keep the configuration surface small — one `config.yaml`, no repo to own | CLI |
| Drive Terraform directly from your laptop and see its output inline | CLI |
| Export metrics from a deployment that's already been torn down | CLI |

## Prerequisites

Every path needs Python 3.10+, `uv`, and Git to install the CLI. What else you need depends on the path:

| Path | Also needs |
|---|---|
| Manual provider | Docker + the `docker compose` v2 plugin, on the allocator host and every client box |
| CLI + AWS | An AWS account and region with the permissions in [AWS Setup](aws-setup.md), the AWS CLI, and Terraform installed locally |
| Template repo | The same AWS account and CLI, plus the GitHub CLI (`gh`) for automated repo setup. GitHub Actions runs Terraform, so you don't install it |

Full install instructions per path: [Prerequisites](prerequisites.md).

## Next steps

- [:material-source-branch: Quickstart: Template repo](quickstart-template.md)
- [:material-console: Quickstart: CLI](cli/first-deployment.md)
- [:material-server-network: Bring-Your-Own Clients](cli/byo-clients.md) — the manual provider, no AWS.
- [CLI Overview](cli/index.md) — deeper comparison of the paths.
