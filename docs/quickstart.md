# Quickstart

LabLink supports two equivalent deployment paths. Both produce the same allocator infrastructure on AWS — they differ in **where Terraform runs** and **where state lives**.

Pick whichever fits your setup. You can switch between them later; both read the same `config.yaml` schema.

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

## Prerequisites (both paths)

Both paths share the same base prerequisites:

- [Prerequisites](prerequisites.md) — AWS account, AWS CLI, Git.
- An AWS region with the permissions listed in [AWS Setup](aws-setup.md).

The template path additionally needs the GitHub CLI (`gh`) for automated repo setup. The CLI path additionally needs Terraform installed locally — see [CLI: Installation](cli/installation.md).

## Next steps

- [:material-source-branch: Quickstart: Template repo](quickstart-template.md)
- [:material-console: Quickstart: CLI](cli/first-deployment.md)
- [CLI Overview](cli/index.md) — deeper comparison of the two paths.
