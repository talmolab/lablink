# Publish Allocator to PyPI

Tag-triggered:

```bash
git tag lablink-allocator-service_v0.1.2
git push origin lablink-allocator-service_v0.1.2
gh run watch
```

Or dispatch manually — note `dry_run` defaults to **true**, so an unset value
builds without publishing:

```bash
gh workflow run publish-pip.yml \
  -f package=lablink-allocator-service -f dry_run=false
```

The version comes from `packages/allocator/pyproject.toml`, not from the workflow
input; bump it there first and make sure the tag matches.
