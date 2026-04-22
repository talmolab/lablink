# Quickstart

LabLink supports two equivalent deployment paths. Both produce the same allocator infrastructure on AWS — they differ in **where Terraform runs** and **where state lives**.

Pick whichever fits your setup. You can switch between them later; both read the same `config.yaml` schema.

<div class="grid cards" markdown>

- :material-source-branch: **Quickstart: Template repo**

    ---

    Create a repository from [lablink-template](https://github.com/talmolab/lablink-template). Push commits to `main` — GitHub Actions runs Terraform with shared S3-backed state.

    Best for **workshops**, shared environments, and **production**: deploys are auditable, reproducible, and anyone with repo access can trigger one.

    [:octicons-arrow-right-24: Quickstart: Template repo](quickstart-template.md)

- :material-console: **Quickstart: CLI**

    ---

    Install the `lablink` CLI and run `lablink configure && lablink deploy` from your own machine. Terraform state lives in an S3 bucket you own.

    Best for **solo iteration**, **local debugging**, and pre-workshop tinkering — no commits, no CI, direct access to Terraform output.

    [:octicons-arrow-right-24: Quickstart: CLI](cli/first-deployment.md)

</div>

## Which path should I pick?

| If you want to… | Use |
|---|---|
| Hand the deployment off to a team via GitHub permissions | Template repo |
| Run reproducible, audited deploys from CI | Template repo |
| Run a workshop where multiple people may trigger deploys | Template repo |
| Stand a deployment up quickly from your laptop | CLI |
| Iterate on config or Terraform changes without pushing commits | CLI |
| Debug a failed deploy with direct Terraform access | CLI |
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
