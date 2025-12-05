# Publish Allocator to PyPI

Publish the allocator package to PyPI using the automated workflow.

## Quick Publish

```bash
# 1. Ensure you're on main branch with latest changes
git checkout main
git pull

# 2. Create version tag (replace version as needed)
git tag lablink-allocator-service_v0.0.2a0
git push origin lablink-allocator-service_v0.0.2a0

# 3. Workflow triggers automatically
# Monitor: gh run watch
```

## Manual Workflow Trigger

```bash
# Trigger manually without tag
gh workflow run publish-pip.yml \
  -f package=allocator \
  -f version=0.0.2a0 \
  -f dry_run=false
```

## Version Tag Format

**Format**: `lablink-allocator-service_v{version}`

**Examples**:
- `lablink-allocator-service_v0.0.2a0` (alpha)
- `lablink-allocator-service_v0.1.0` (stable)

## Pre-Publication Checklist

Before creating the tag:

```bash
# 1. Verify version in pyproject.toml
cat packages/allocator/pyproject.toml | grep "version ="

# 2. Run tests
cd packages/allocator
PYTHONPATH=. pytest --cov

# 3. Run linting
ruff check packages/allocator

# 4. Verify package builds
cd packages/allocator
uv build

# 5. Check CHANGELOG updated
cat CHANGELOG.md
```

## Dry Run (Test)

Test the publish process without uploading:

```bash
gh workflow run publish-pip.yml \
  -f package=allocator \
  -f version=0.0.2a0 \
  -f dry_run=true
```

This will:
- Build the package
- Run tests
- Validate metadata
- **NOT** upload to PyPI

## Workflow Steps

The `publish-pip.yml` workflow:
1. **Branch verification**: Ensures tag is from main branch
2. **Version verification**: Tag version matches `pyproject.toml`
3. **Metadata validation**: Package metadata is valid
4. **Linting**: Runs `ruff check`
5. **Tests**: Runs pytest with coverage
6. **Build**: Creates wheel and sdist
7. **Publish**: Uploads to PyPI (if not dry run)
8. **Post-publish message**: Shows Docker build command

## After Publishing

After successful publish:

```bash
# 1. Verify package on PyPI
pip index versions lablink-allocator

# 2. Wait 5-10 minutes for propagation

# 3. Trigger Docker production builds
gh workflow run lablink-images.yml \
  -f environment=prod \
  -f allocator_version=0.0.2a0 \
  -f client_version=0.0.7a0
```

## View Workflow Status

```bash
# List recent publish runs
gh run list --workflow=publish-pip.yml

# Watch latest run
gh run watch

# View specific run
gh run view <run-id> --log
```

## Version Bumping

### Alpha Versions
For pre-release/testing:
```
0.0.1a0 → 0.0.2a0 → 0.0.3a0
```

### Stable Versions
Following [Semantic Versioning](https://semver.org/):
- **Patch** (bug fixes): `0.1.0` → `0.1.1`
- **Minor** (new features): `0.1.0` → `0.2.0`
- **Major** (breaking changes): `0.1.0` → `1.0.0`

## Verify Published Package

```bash
# Check PyPI
pip index versions lablink-allocator

# Install in clean environment
uv venv test-env
source test-env/bin/activate  # Unix
# test-env\Scripts\activate  # Windows
pip install lablink-allocator==0.0.2a0

# Test entry point
lablink-allocator --help
```

## Troubleshooting

### Tag Already Exists
**Symptom**: `error: tag already exists`

**Solutions**:
```bash
# Delete local tag
git tag -d lablink-allocator-service_v0.0.2a0

# Delete remote tag
git push origin --delete lablink-allocator-service_v0.0.2a0

# Recreate with correct version
git tag lablink-allocator-service_v0.0.3a0
git push origin lablink-allocator-service_v0.0.3a0
```

### Version Mismatch
**Symptom**: Workflow fails with "version mismatch"

**Solutions**:
1. Check tag: `lablink-allocator-service_v0.0.2a0`
2. Check `pyproject.toml`: `version = "0.0.2a0"`
3. Ensure versions match exactly

### Not on Main Branch
**Symptom**: Workflow fails "must be from main branch"

**Solutions**:
```bash
# Verify current branch
git branch --show-current

# Switch to main
git checkout main
git pull

# Recreate tag
git tag -d lablink-allocator-service_v0.0.2a0
git tag lablink-allocator-service_v0.0.2a0
git push origin lablink-allocator-service_v0.0.2a0
```

### PyPI Upload Fails
**Symptom**: Build succeeds but upload fails

**Solutions**:
1. Check PyPI credentials in GitHub Secrets
2. Verify package name not taken by other user
3. Ensure you have permissions to upload to talmolab org

## Related Commands

- `/publish-client` - Publish client package
- `/trigger-docker-build` - Build Docker images after publish
- `/update-changelog` - Update changelog before publishing