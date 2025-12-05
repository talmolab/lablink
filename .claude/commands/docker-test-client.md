# Test Client Docker Container

Run functional tests on the client Docker container to verify proper operation.

## Quick Test Suite

```bash
# Build image first
docker build -t lablink-client:dev -f packages/client/Dockerfile.dev .

# Test 1: Entry points are callable
docker run --rm lablink-client:dev subscribe --help
docker run --rm lablink-client:dev check_gpu --help
docker run --rm lablink-client:dev update_inuse_status --help

# Test 2: Console scripts exist
docker run --rm lablink-client:dev bash -c "which subscribe && which check_gpu && which update_inuse_status"

# Test 3: Virtual environment is activated
docker run --rm lablink-client:dev bash -c "which python && python --version"

# Test 4: Package imports work
docker run --rm lablink-client:dev python -c "from lablink_client import subscribe, check_gpu, update_inuse_status; print('Imports OK')"

# Test 5: CUDA is available (requires --gpus flag)
docker run --rm --gpus all lablink-client:dev python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"
```

## Individual Test Details

### Test 1: Entry Point Verification

```bash
# Test subscribe entry point
docker run --rm lablink-client:dev subscribe --help

# Test check_gpu entry point
docker run --rm lablink-client:dev check_gpu --help

# Test update_inuse_status entry point
docker run --rm lablink-client:dev update_inuse_status --help
```

**Expected output**: Help messages showing available options (not errors).

### Test 2: Console Scripts Path

```bash
# Verify all scripts are in PATH
docker run --rm lablink-client:dev bash -c "
  which subscribe && \
  which check_gpu && \
  which update_inuse_status && \
  echo 'All console scripts found'
"
```

**Expected output**:
```
/home/client/.venv/bin/subscribe
/home/client/.venv/bin/check_gpu
/home/client/.venv/bin/update_inuse_status
All console scripts found
```

### Test 3: Virtual Environment Activation

```bash
# Check venv is active
docker run --rm lablink-client:dev bash -c "
  echo 'Python: '$(which python) && \
  echo 'Version: '$(python --version) && \
  echo 'Venv: '$VIRTUAL_ENV
"
```

**Expected output**:
```
Python: /home/client/.venv/bin/python
Version: Python 3.10.x
Venv: /home/client/.venv
```

### Test 4: Package Imports

```bash
# Test critical imports
docker run --rm lablink-client:dev python -c "
from lablink_client import subscribe, check_gpu, update_inuse_status
from lablink_client.conf import config
print('All imports successful')
"
```

**Expected output**: `All imports successful`

### Test 5: GPU/CUDA Support

```bash
# Test CUDA availability (requires nvidia-docker and --gpus flag)
docker run --rm --gpus all lablink-client:dev python -c "
import torch
print(f'PyTorch version: {torch.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'CUDA version: {torch.version.cuda}')
    print(f'GPU count: {torch.cuda.device_count()}')
"
```

**Expected output** (with GPU):
```
PyTorch version: 2.x.x
CUDA available: True
CUDA version: 12.8
GPU count: 1
```

**Without GPU**: `CUDA available: False` (expected on non-GPU systems)

### Test 6: Dev Dependencies Present

```bash
# Verify dev tools installed (Dockerfile.dev only)
docker run --rm lablink-client:dev bash -c "
  pytest --version && \
  ruff --version && \
  uv --version && \
  echo 'Dev dependencies OK'
"
```

**Expected output**:
```
pytest 8.x.x
ruff 0.x.x
uv 0.x.x
Dev dependencies OK
```

### Test 7: Configuration Loading

```bash
# Test config loading
docker run --rm lablink-client:dev python -c "
from lablink_client.conf.config import cfg
print(f'Software: {cfg.client.software}')
print(f'Allocator host: {cfg.allocator.host}')
"
```

**Expected output**: Shows default config values.

### Test 8: Start Script Works

```bash
# Test the start.sh entry point script
docker run --rm lablink-client:dev bash -c "cat /home/client/start.sh && echo '---' && bash -n /home/client/start.sh && echo 'Syntax OK'"
```

**Expected output**: Script contents followed by `Syntax OK`.

## Full Container Test with Mock Allocator

```bash
# Run client services with mock allocator
docker run --rm \
  -e ALLOCATOR_URL=http://mock-allocator:5000 \
  -e CLIENT_SOFTWARE=test-software \
  lablink-client:dev
```

**Note**: Will fail to connect to allocator (expected), but verifies services start.

## GPU Test (Requires NVIDIA Runtime)

```bash
# Full GPU test with all services
docker run --rm --gpus all \
  -e ALLOCATOR_URL=http://mock-allocator:5000 \
  lablink-client:dev bash -c "
    check_gpu --dry-run && \
    echo 'GPU check OK'
  "
```

## Windows PowerShell Examples

```powershell
# Test entry points
docker run --rm lablink-client:dev subscribe --help

# Test imports with PowerShell quoting
docker run --rm lablink-client:dev python -c "from lablink_client import subscribe; print('OK')"

# GPU test (requires nvidia-docker on Windows with WSL2)
docker run --rm --gpus all lablink-client:dev python -c "import torch; print(torch.cuda.is_available())"
```

## Automated Test Script

Create `scripts/test-docker-client.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

IMAGE="lablink-client:dev"

echo "Testing client Docker image..."

echo "✓ Test 1: Entry points"
docker run --rm "$IMAGE" subscribe --help > /dev/null
docker run --rm "$IMAGE" check_gpu --help > /dev/null
docker run --rm "$IMAGE" update_inuse_status --help > /dev/null

echo "✓ Test 2: Console scripts"
docker run --rm "$IMAGE" bash -c "which subscribe && which check_gpu && which update_inuse_status" > /dev/null

echo "✓ Test 3: Virtual environment"
docker run --rm "$IMAGE" bash -c "test -n '$VIRTUAL_ENV'" > /dev/null

echo "✓ Test 4: Imports"
docker run --rm "$IMAGE" python -c "from lablink_client import subscribe, check_gpu, update_inuse_status" > /dev/null

echo "✓ Test 5: Dev dependencies"
docker run --rm "$IMAGE" bash -c "pytest --version && ruff --version && uv --version" > /dev/null

echo "✓ Test 6: PyTorch import"
docker run --rm "$IMAGE" python -c "import torch; print('PyTorch OK')" > /dev/null

# Optional GPU test (only if nvidia-docker available)
if command -v nvidia-smi &> /dev/null; then
    echo "✓ Test 7: CUDA availability"
    docker run --rm --gpus all "$IMAGE" python -c "import torch; torch.cuda.is_available()" > /dev/null
fi

echo "All tests passed!"
```

## CI Integration

**Note**: Client Docker build tests are skipped in CI due to large image size (~6GB). Similar tests run in the workflow but are commented out to save build time.

## Troubleshooting

### Entry Points Not Found
**Symptom**: `bash: subscribe: command not found`

**Solutions**:
1. Verify entry points exist: `docker run --rm image bash -c "which subscribe"`
2. Check venv activation in start.sh: `docker run --rm image cat /home/client/start.sh`
3. Rebuild image: `docker build --no-cache ...`

### CUDA Not Available
**Symptom**: `torch.cuda.is_available()` returns `False`

**Solutions**:
1. Verify host has GPU: `nvidia-smi`
2. Install nvidia-docker: `sudo apt-get install nvidia-docker2`
3. Use `--gpus all` flag: `docker run --gpus all ...`
4. Restart Docker daemon: `sudo systemctl restart docker`

### Import Errors
**Symptom**: `ModuleNotFoundError: No module named 'lablink_client'`

**Solutions**:
1. Verify venv is activated: `docker run --rm image bash -c "echo $VIRTUAL_ENV"`
2. Check package installed: `docker run --rm image pip list | grep lablink`
3. Verify installation: `docker run --rm image pip show lablink-client`

### Container Exits Immediately
**Symptom**: Container starts but exits right away

**Solutions**:
1. Check logs: `docker logs <container-id>`
2. Run with interactive shell: `docker run -it image bash`
3. Override entrypoint: `docker run --entrypoint bash -it image`
4. Check start.sh for errors: `docker run --rm image bash -n /home/client/start.sh`

### Large Image Size
**Symptom**: Image is 6+ GB

**Note**: This is expected due to NVIDIA CUDA base image (~5GB). Client images are inherently large.

## Related Commands

- `/docker-build-client` - Build client images
- `/docker-test-allocator` - Test allocator container
- `/test-client` - Run unit tests