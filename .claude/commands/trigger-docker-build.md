# Trigger Docker Image Build

Manually trigger the Docker image build workflow to create and publish container images.

## Production Build with Versions

```bash
# Build production images with specific versions
gh workflow run lablink-images.yml \
  -f environment=prod \
  -f allocator_version=0.0.2a0 \
  -f client_version=0.0.7a0
```

This creates:
- `ghcr.io/talmolab/lablink-allocator-image:0.0.2a0`
- `ghcr.io/talmolab/lablink-client-base-image:0.0.7a0`
- Plus `latest`, platform, and metadata tags

## Development Build (Test Branch)

```bash
# Trigger dev build on test branch
gh workflow run lablink-images.yml --ref test

# Or manually dispatch for dev environment
gh workflow run lablink-images.yml -f environment=dev
```

This creates images with `-test` suffix using `Dockerfile.dev`.

## Workflow Inputs

```bash
# Full parameter specification
gh workflow run lablink-images.yml \
  -f environment=prod \
  -f allocator_version=0.0.2a0 \
  -f client_version=0.0.7a0 \
  -f build_allocator=true \
  -f build_client=true
```

### Parameters
- `environment`: `prod` or `dev` (default: auto-detect from branch)
- `allocator_version`: PyPI version for allocator (required for prod)
- `client_version`: PyPI version for client (required for prod)
- `build_allocator`: Build allocator image (default: true)
- `build_client`: Build client image (default: true)

## Build Specific Image Only

```bash
# Build only allocator
gh workflow run lablink-images.yml \
  -f environment=prod \
  -f allocator_version=0.0.2a0 \
  -f build_client=false

# Build only client
gh workflow run lablink-images.yml \
  -f environment=prod \
  -f client_version=0.0.7a0 \
  -f build_allocator=false
```

## View Build Progress

```bash
# List recent workflow runs
gh run list --workflow=lablink-images.yml

# Watch latest run
gh run watch

# View specific run logs
gh run view <run-id> --log
```

## After Publishing to PyPI

After publishing packages to PyPI, trigger production builds:

```bash
# 1. Publish to PyPI (see /publish-allocator or /publish-client)

# 2. Wait for PyPI propagation (~5 minutes)

# 3. Trigger production Docker builds
gh workflow run lablink-images.yml \
  -f environment=prod \
  -f allocator_version=0.0.2a0 \
  -f client_version=0.0.7a0
```

## Automatic Triggers

The workflow runs automatically on:
- **PRs** affecting Dockerfiles or package code (builds dev images)
- **Pushes to test branch** (builds dev images with `-test` tags)
- **Pushes to main branch** (builds latest from PyPI, no version tags)

## Expected Duration

- **Allocator build**: ~5-8 minutes
- **Client build**: ~20-30 minutes (large CUDA image)
- **Both builds**: ~25-35 minutes total

## Image Tags

### Production Build Tags (environment=prod)
- `0.0.2a0` - Version tag
- `linux-amd64-0.0.2a0` - Platform-specific version
- `latest` - Latest production build
- `linux-amd64-latest` - Platform-specific latest
- `<commit-sha>` - Git commit SHA
- Plus build metadata tags

### Development Build Tags (environment=dev or test branch)
- All above tags with `-test` suffix
- Example: `latest-test`, `linux-amd64-0.0.2a0-test`

## Verify Images Published

```bash
# List allocator images
gh api /user/packages/container/lablink-allocator-image/versions | jq '.[].metadata.container.tags'

# List client images
gh api /user/packages/container/lablink-client-base-image/versions | jq '.[].metadata.container.tags'

# Or visit GitHub Packages UI
# https://github.com/orgs/talmolab/packages
```

## Troubleshooting

### Build Fails: Package Not Found on PyPI
**Symptom**: Production build can't find `lablink-allocator==0.0.2a0`

**Solutions**:
1. Verify package published: `pip index versions lablink-allocator`
2. Wait 5-10 minutes for PyPI propagation
3. Check version matches exactly (including alpha suffix)

### Build Timeout
**Symptom**: Client build times out (>60 minutes)

**Solutions**:
1. Client builds are slow due to CUDA (~20-30 min normal)
2. Check GitHub Actions status for outages
3. Re-run the workflow: `gh run rerun <run-id>`

### Permission Denied to Push Images
**Symptom**: Build succeeds but push to GHCR fails

**Solutions**:
1. Check repository has GHCR permissions enabled
2. Verify GitHub Actions has write access to packages
3. Check GITHUB_TOKEN permissions in workflow

### Wrong Dockerfile Used
**Symptom**: Production build uses dev Dockerfile or vice versa

**Solutions**:
1. Verify `environment` parameter: `prod` vs `dev`
2. Check workflow run inputs: `gh run view <run-id>`
3. Ensure version parameters provided for prod builds

## Related Commands

- `/publish-allocator` - Publish allocator to PyPI first
- `/publish-client` - Publish client to PyPI first
- `/docker-build-allocator` - Build images locally
- `/docker-build-client` - Build images locally