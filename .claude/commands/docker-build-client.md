# Build Client Docker Images

Build Docker images for the client service (both development and production variants).

## Quick Commands

```bash
# Build development image (uses local code)
docker build -t lablink-client:dev -f packages/client/Dockerfile.dev .

# Build production image (from PyPI)
docker build -t lablink-client:0.0.7a0 \
  --build-arg PACKAGE_VERSION=0.0.7a0 \
  -f packages/client/Dockerfile .
```

## Development Build (Dockerfile.dev)

### Basic Build

```bash
# Build from local code with dev dependencies
docker build -t lablink-client:dev -f packages/client/Dockerfile.dev .
```

### What's Included
- Local source code from `packages/client/`
- Virtual environment at `/home/client/.venv`
- Python 3.10 (Ubuntu 22.04 default)
- NVIDIA CUDA 12.8.1 base image
- GPU support enabled
- Dev dependencies (pytest, ruff, coverage)
- Console scripts: `subscribe`, `check_gpu`, `update_inuse_status`

### Build Time
- **First build**: ~15-25 minutes (large CUDA base image ~6GB)
- **Subsequent builds**: ~2-5 minutes (layer caching)

**Note**: Client images are significantly larger and slower to build due to NVIDIA CUDA dependencies.

## Production Build (Dockerfile)

### Basic Build

```bash
# Build from PyPI package
docker build -t lablink-client:0.0.7a0 \
  --build-arg PACKAGE_VERSION=0.0.7a0 \
  -f packages/client/Dockerfile .
```

### With Multiple Tags

```bash
# Tag as both versioned and latest
docker build -t lablink-client:0.0.7a0 \
  -t lablink-client:latest \
  --build-arg PACKAGE_VERSION=0.0.7a0 \
  -f packages/client/Dockerfile .
```

### What's Included
- Package installed from PyPI (`lablink-client==0.0.7a0`)
- Virtual environment at `/home/client/.venv`
- Python 3.10
- NVIDIA CUDA 12.8.1 runtime
- GPU support enabled
- Production dependencies only

## Platform Considerations

### NVIDIA GPU Support

```bash
# Build requires CUDA base image (linux/amd64 only)
docker build --platform linux/amd64 \
  -t lablink-client:dev \
  -f packages/client/Dockerfile.dev .
```

**Note**: ARM builds not supported due to CUDA dependencies.

## Verify Build

### Check Image Exists

```bash
docker images lablink-client
```

Expected output:
```
REPOSITORY        TAG       IMAGE ID       CREATED          SIZE
lablink-client    dev       abc123def456   10 minutes ago   6.2GB
lablink-client    0.0.7a0   def789ghi012   15 minutes ago   5.8GB
```

### Test Entry Points

```bash
# Test subscribe entry point
docker run --rm lablink-client:dev subscribe --help

# Test check_gpu entry point
docker run --rm lablink-client:dev check_gpu --help

# Test update_inuse_status entry point
docker run --rm lablink-client:dev update_inuse_status --help
```

### Verify GPU Support (Requires NVIDIA Runtime)

```bash
# Test GPU detection (requires nvidia-docker)
docker run --rm --gpus all lablink-client:dev python -c "import torch; print(torch.cuda.is_available())"
```

## Build for GitHub Container Registry

```bash
# Build with GHCR tag
docker build -t ghcr.io/talmolab/lablink-client-base-image:0.0.7a0 \
  --build-arg PACKAGE_VERSION=0.0.7a0 \
  -f packages/client/Dockerfile .

# Push to GHCR (requires authentication)
docker push ghcr.io/talmolab/lablink-client-base-image:0.0.7a0
```

## Build Options

### No Cache

```bash
# Force rebuild without cache (takes longer)
docker build --no-cache -t lablink-client:dev \
  -f packages/client/Dockerfile.dev .
```

### Specify Build Resources

```bash
# Allocate more memory for build (recommended for client)
docker build --memory=8g -t lablink-client:dev \
  -f packages/client/Dockerfile.dev .
```

## Troubleshooting

### Build Fails During CUDA Base Image Pull
**Symptom**: Timeout or network error pulling NVIDIA image

**Solutions**:
1. Check internet connection
2. Retry the build (transient network issues)
3. Use Docker Hub mirror if available

### Build Extremely Slow
**Symptom**: Build takes >30 minutes

**Solutions**:
1. First build is always slow (downloading 6GB CUDA image)
2. Ensure Docker has enough memory allocated (8GB+ recommended)
3. Use layer caching for subsequent builds
4. Consider building on faster network connection

### Out of Disk Space

```bash
# Check disk usage
docker system df

# Clean up (WARNING: removes all unused images/containers)
docker system prune -a

# Remove specific large images
docker rmi lablink-client:dev
```

### Production Build Can't Find Package
**Symptom**: `ERROR: Could not find a version that satisfies the requirement lablink-client==0.0.7a0`

**Solutions**:
1. Ensure package is published to PyPI
2. Check version exists: `pip index versions lablink-client`
3. Wait a few minutes after publishing (PyPI propagation)

### GPU Tests Fail
**Symptom**: Cannot detect GPU in container

**Solutions**:
1. Install nvidia-docker: `sudo apt-get install nvidia-docker2`
2. Use `--gpus all` flag: `docker run --gpus all ...`
3. Verify host has GPU: `nvidia-smi`

## CI Integration

Docker images are built automatically in `.github/workflows/lablink-images.yml`:
- **Development images**: Built on PRs and test branch pushes
- **Production images**: Built via manual dispatch with version parameters

**Note**: Client Docker build tests are skipped in CI due to large image size (~6GB).

## Related Commands

- `/docker-test-client` - Test client container
- `/docker-build-allocator` - Build allocator images
- `/trigger-docker-build` - Trigger GitHub Actions workflow