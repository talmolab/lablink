# Trigger Docker Image Build

```bash
# Test images from the current branch
gh workflow run lablink-images.yml --ref <branch> -f environment=test

# Production images — versions are REQUIRED for prod
gh workflow run lablink-images.yml -f environment=prod \
  -f allocator_version=0.1.2 -f client_version=0.1.2
```

Inputs are exactly `environment` (`test` | `ci-test` | `prod`),
`allocator_version`, and `client_version`. The workflow also runs automatically on
PRs and on pushes to `main`/`test` that touch the packages.

See `docs/workflows.md` for the image tagging scheme.
