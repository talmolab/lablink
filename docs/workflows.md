# Workflows

This repository's GitHub Actions workflows test, publish, and document the
three LabLink packages. The OpenTofu deployment workflows live in the
[template repository](https://github.com/talmolab/lablink-template); see
[Template Repository Deployment](deployment.md).

## Continuous Integration Workflow

`.github/workflows/ci.yml` runs lint and unit tests for package changes on
pull requests. The allocator and client jobs enforce a 90% coverage gate; the
allocator's OpenTofu tests also need an AWS role. Docker image builds run in
`lablink-images.yml`, not this workflow.

## Package Publishing Workflow

`.github/workflows/publish-pip.yml` publishes
`lablink-allocator-service`, `lablink-client-service`, or `lablink-cli` to
PyPI. It runs for package tags (for example,
`lablink-allocator-service_v0.4.0`), published GitHub releases, or manual
dispatch. Manual dispatch chooses `package` and offers `dry_run` (default
`true`) and `skip_tests` (default `false`). A release and tag push for the
same version are serialized; the later run skips an existing PyPI version.

Publish the allocator and client packages before building production images
from them:

```bash
gh workflow run lablink-images.yml \
  -f environment=prod \
  -f allocator_version=0.4.0 \
  -f client_version=0.4.0
```

The versions must match packages already published to PyPI. Production
images are built from the package-installing `Dockerfile`; automated pushes
and pull requests use `Dockerfile.dev` and local source.

## Image Building Workflow

`.github/workflows/lablink-images.yml` builds
`ghcr.io/talmolab/lablink-allocator-image` and
`ghcr.io/talmolab/lablink-client-base-image`.

| Trigger | Source | Main tags |
|---|---|---|
| Pull request; push to `main` or `test`; manual `test` or `ci-test` | Local code via `Dockerfile.dev` | `:linux-amd64-test`, `:linux-amd64-<sha>-test`, `:linux-amd64-latest-test` |
| Manual `prod` with both package versions | Published PyPI packages via `Dockerfile` | `:<version>`, `:linux-amd64-<version>`, `:latest`, `:linux-amd64-latest` |

Set `allocator.image_tag` and `machine.image` in `config.yaml` to select
images for a deployment. They are not OpenTofu `-var` inputs. For example:

```yaml
allocator:
  image_tag: "linux-amd64-0.4.0"
machine:
  image: "ghcr.io/talmolab/lablink-client-base-image:linux-amd64-0.4.0"
```

The workflow also pushes tags describing base components. Those tag names
currently include stale `postgres-15` and `cudnn8-devel` strings; they do
not describe the actual PostgreSQL 17 allocator or current client base.
Supplying version inputs on a manual `test` or `ci-test` run currently pushes
unsuffixed version tags even though the image is built from local source.
Leave those inputs empty for development runs.

## Documentation Workflow

`.github/workflows/docs.yml` builds the MkDocs site on pull requests that
change `docs/**` or `mkdocs.yml`, and on manual dispatch. On `main`, it
deploys the site when those paths, the workflow file, or allocator/client
Python files change. The latter two paths matter because the API reference
is generated from route docstrings. The CI build uses `mkdocs build` without
`--strict`.
