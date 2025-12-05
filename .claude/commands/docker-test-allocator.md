# Test Allocator Docker Container

Run functional tests on the allocator Docker container to verify proper operation.

## Quick Test Suite

```bash
# Build image first
docker build -t lablink-allocator:dev -f packages/allocator/Dockerfile.dev .

# Test 1: Entry point is callable
docker run --rm lablink-allocator:dev lablink-allocator --help

# Test 2: Console scripts exist
docker run --rm lablink-allocator:dev bash -c "which lablink-allocator && which generate-init-sql"

# Test 3: Virtual environment is activated
docker run --rm lablink-allocator:dev bash -c "which python && python --version"

# Test 4: Package imports work
docker run --rm lablink-allocator:dev python -c "from lablink_allocator import main, database, get_config; print('Imports OK')"

# Test 5: Dev dependencies installed
docker run --rm lablink-allocator:dev bash -c "pip list | grep -E 'pytest|ruff|coverage'"
```

## Individual Test Details

### Test 1: Entry Point Verification

```bash
# Test lablink-allocator entry point
docker run --rm lablink-allocator:dev lablink-allocator --help

# Test generate-init-sql entry point
docker run --rm lablink-allocator:dev generate-init-sql --help
```

**Expected output**: Help message showing available options (not an error).

### Test 2: Console Scripts Path

```bash
# Verify scripts are in PATH
docker run --rm lablink-allocator:dev bash -c "
  which lablink-allocator && \
  which generate-init-sql && \
  echo 'Console scripts found'
"
```

**Expected output**:
```
/app/.venv/bin/lablink-allocator
/app/.venv/bin/generate-init-sql
Console scripts found
```

### Test 3: Virtual Environment Activation

```bash
# Check venv is active
docker run --rm lablink-allocator:dev bash -c "
  echo 'Python: '$(which python) && \
  echo 'Version: '$(python --version) && \
  echo 'Venv: '$VIRTUAL_ENV
"
```

**Expected output**:
```
Python: /app/.venv/bin/python
Version: Python 3.11.x
Venv: /app/.venv
```

### Test 4: Package Imports

```bash
# Test critical imports
docker run --rm lablink-allocator:dev python -c "
from lablink_allocator import main, database, get_config
from lablink_allocator.conf import structured_config
print('All imports successful')
"
```

**Expected output**: `All imports successful`

### Test 5: Dev Dependencies Present

```bash
# Verify dev tools installed (Dockerfile.dev only)
docker run --rm lablink-allocator:dev bash -c "
  pytest --version && \
  ruff --version && \
  echo 'Dev dependencies OK'
"
```

**Expected output**:
```
pytest 8.x.x
ruff 0.x.x
Dev dependencies OK
```

### Test 6: Configuration Loading

```bash
# Test config loading (should use bundled config)
docker run --rm lablink-allocator:dev python -c "
from lablink_allocator.get_config import get_config
cfg = get_config()
print(f'Database: {cfg.db.dbname}')
print(f'Region: {cfg.app.region}')
"
```

**Expected output**: Shows default config values.

### Test 7: Terraform Files Present

```bash
# Verify Terraform files are included
docker run --rm lablink-allocator:dev bash -c "
  ls /app/.venv/lib/python3.11/site-packages/lablink_allocator/terraform/*.tf && \
  echo 'Terraform files present'
"
```

**Expected output**: Lists `main.tf`, `variables.tf`, `outputs.tf`.

## Full Container Test

Run allocator with minimal config:

```bash
# Create test config
cat > /tmp/test_config.yaml << 'EOF'
db:
  host: localhost
  port: 5432
  dbname: test
  user: test
  password: test

app:
  admin_password: test
  region: us-east-1

machine:
  instance_type: t3.micro
  ami_id: ami-12345
  docker_image: test
  docker_repo: test

bucket_name: test-bucket
EOF

# Run allocator with test config
docker run --rm \
  -v /tmp/test_config.yaml:/config/config.yaml:ro \
  -e FLASK_ENV=development \
  -p 5000:5000 \
  lablink-allocator:dev
```

**Note**: This will fail at database connection (expected), but verifies the application starts.

## Windows PowerShell Examples

```powershell
# Test entry points
docker run --rm lablink-allocator:dev lablink-allocator --help

# Test imports with PowerShell quoting
docker run --rm lablink-allocator:dev python -c "from lablink_allocator import main; print('OK')"

# Volume mount for config (Windows paths)
docker run --rm `
  -v ${PWD}/config.yaml:/config/config.yaml:ro `
  lablink-allocator:dev
```

## Automated Test Script

Create `scripts/test-docker-allocator.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

IMAGE="lablink-allocator:dev"

echo "Testing allocator Docker image..."

echo "✓ Test 1: Entry point"
docker run --rm "$IMAGE" lablink-allocator --help > /dev/null

echo "✓ Test 2: Console scripts"
docker run --rm "$IMAGE" bash -c "which lablink-allocator && which generate-init-sql" > /dev/null

echo "✓ Test 3: Virtual environment"
docker run --rm "$IMAGE" bash -c "test -n '$VIRTUAL_ENV'" > /dev/null

echo "✓ Test 4: Imports"
docker run --rm "$IMAGE" python -c "from lablink_allocator import main, database, get_config" > /dev/null

echo "✓ Test 5: Dev dependencies"
docker run --rm "$IMAGE" bash -c "pytest --version && ruff --version" > /dev/null

echo "All tests passed!"
```

## CI Integration

Similar tests run automatically in `.github/workflows/ci.yml` after Docker builds:
- Verify entry points are callable
- Check console scripts exist
- Validate imports
- Verify dev dependencies

## Troubleshooting

### Entry Point Not Found
**Symptom**: `docker: Error response from daemon: failed to create task for container: failed to create shim task: OCI runtime create failed`

**Solutions**:
1. Verify entry point exists: `docker run --rm image bash -c "which lablink-allocator"`
2. Check `start.sh` activates venv: `docker run --rm image cat /app/start.sh`
3. Rebuild image: `docker build --no-cache ...`

### Import Errors
**Symptom**: `ModuleNotFoundError: No module named 'lablink_allocator'`

**Solutions**:
1. Verify venv is activated: `docker run --rm image bash -c "echo $VIRTUAL_ENV"`
2. Check package installed: `docker run --rm image pip list | grep lablink`
3. Verify PYTHONPATH: `docker run --rm image bash -c "echo $PYTHONPATH"`

### Container Exits Immediately
**Symptom**: Container starts but exits right away

**Solutions**:
1. Check logs: `docker logs <container-id>`
2. Run with interactive shell: `docker run -it image bash`
3. Override entrypoint: `docker run --entrypoint bash -it image`

## Related Commands

- `/docker-build-allocator` - Build allocator images
- `/docker-test-client` - Test client container
- `/test-allocator` - Run unit tests