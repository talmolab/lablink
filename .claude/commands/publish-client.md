# Publish Client to PyPI

Tag-triggered:

```bash
git tag lablink-client-service_v0.1.2
git push origin lablink-client-service_v0.1.2
gh run watch
```

Or dispatch manually (`dry_run` defaults to **true**):

```bash
gh workflow run publish-pip.yml \
  -f package=lablink-client-service -f dry_run=false
```

The version comes from `packages/client/pyproject.toml`. `lablink-cli` publishes
through the same workflow with `-f package=lablink-cli`.

Production Dockerfiles install from PyPI, so an image only picks up these changes
after the publish lands.
