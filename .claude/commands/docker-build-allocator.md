# Build Allocator Docker Images

Build Docker images for the allocator service (both development and production variants).

## Quick Commands

```bash
# Build development image (uses local code)
docker build -t lablink-allocator:dev -f packages/allocator/Dockerfile.dev .

# Build production image (from PyPI)
docker build -t lablink-allocator:0.0.2a0 \
  --build-arg PACKAGE_VERSION=0.0.2a0 \
  -f packages/allocator/Dockerfile .
```

## Development Build (Dockerfile.dev)

### Basic Build

```bash
# Build from local code with dev dependencies
docker build -t lablink-allocator:dev -f packages/allocator/Dockerfile.dev .
```

### What's Included
- Local source code from `packages/allocator/`
- Virtual environment at `/app/.venv`
- Python 3.11 (from `ghcr.io/astral-sh/uv:python3.11`)
- Dev dependencies (pytest, ruff, coverage)
- `uv sync --extra dev` with lockfile
- Console scripts: `lablink-allocator`, `generate-init-sql`

### Build Time
- **First build**: ~3-5 minutes (downloads dependencies)
- **Subsequent builds**: ~30-60 seconds (layer caching)

## Production Build (Dockerfile)

### Basic Build

```bash
# Build from PyPI package
docker build -t lablink-allocator:0.0.2a0 \
  --build-arg PACKAGE_VERSION=0.0.2a0 \
  -f packages/allocator/Dockerfile .
```

### With Multiple Tags

```bash
# Tag as both versioned and latest
docker build -t lablink-allocator:0.0.2a0 \
  -t lablink-allocator:latest \
  --build-arg PACKAGE_VERSION=0.0.2a0 \
  -f packages/allocator/Dockerfile .
```

### What's Included
- Package installed from PyPI (`lablink-allocator==0.0.2a0`)
- Virtual environment at `/app/.venv`
- Python 3.11
- Production dependencies only (no dev tools)
- Smaller image size (no local source code)

## Multi-Platform Build

```bash
# Build for linux/amd64 (most common)
docker build --platform linux/amd64 \
  -t lablink-allocator:dev \
  -f packages/allocator/Dockerfile.dev .

# Build for multiple platforms
docker buildx build --platform linux/amd64,linux/arm64 \
  -t lablink-allocator:dev \
  -f packages/allocator/Dockerfile.dev .
```

## Verify Build

### Check Image Exists

```bash
docker images lablink-allocator
```

Expected output:
```
REPOSITORY           TAG       IMAGE ID       CREATED         SIZE
lablink-allocator    dev       abc123def456   2 minutes ago   450MB
lablink-allocator    0.0.2a0   def789ghi012   5 minutes ago   380MB
```

### Test Entry Point

```bash
# Test that allocator starts
docker run --rm lablink-allocator:dev lablink-allocator --help

# Should show Flask/allocator help message
```

### Verify Console Scripts

```bash
# Check lablink-allocator entry point
docker run --rm lablink-allocator:dev bash -c "which lablink-allocator"

# Check generate-init-sql entry point
docker run --rm lablink-allocator:dev bash -c "which generate-init-sql"
```

## Build for GitHub Container Registry

```bash
# Build with GHCR tag
docker build -t ghcr.io/talmolab/lablink-allocator-image:0.0.2a0 \
  --build-arg PACKAGE_VERSION=0.0.2a0 \
  -f packages/allocator/Dockerfile .

# Push to GHCR (requires authentication)
docker push ghcr.io/talmolab/lablink-allocator-image:0.0.2a0
```

## Build Options

### No Cache

```bash
# Force rebuild without cache
docker build --no-cache -t lablink-allocator:dev \
  -f packages/allocator/Dockerfile.dev .
```

### Specify Python Version

```bash
# Use different Python version (must match base image)
docker build -t lablink-allocator:dev \
  --build-arg PYTHON_VERSION=3.11 \
  -f packages/allocator/Dockerfile.dev .
```

## Troubleshooting

### Build Fails During uv sync
**Symptom**: Error during dependency installation

**Solutions**:
1. Check internet connection (downloads from PyPI)
2. Verify `uv.lock` is up to date: `cd packages/allocator && uv sync`
3. Try building without cache: `docker build --no-cache ...`

### Production Build Can't Find Package
**Symptom**: `ERROR: Could not find a version that satisfies the requirement lablink-allocator==0.0.2a0`

**Solutions**:
1. Ensure package is published to PyPI
2. Check version exists: `pip index versions lablink-allocator`
3. Wait a few minutes after publishing (PyPI propagation)

### Out of Disk Space

```bash
# Clean up old images and build cache
docker system prune -a

# Remove specific images
docker rmi lablink-allocator:dev
```

### Permission Denied

```bash
# On Linux, add user to docker group
sudo usermod -aG docker $USER
newgrp docker
```

## CI Integration

Docker images are built automatically in `.github/workflows/lablink-images.yml`:
- **Development images**: Built on PRs and test branch pushes
- **Production images**: Built via manual dispatch with version parameters

## Related Commands

- `/docker-test-allocator` - Test allocator container
- `/docker-build-client` - Build client images
- `/trigger-docker-build` - Trigger GitHub Actions workflow