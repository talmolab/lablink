# Run Client Unit Tests

Run unit tests for the client package using pytest.

## Command

```bash
cd packages/client
uv run pytest
```

## With Verbose Output

```bash
cd packages/client
uv run pytest -v
```

## Run Specific Test File

```bash
cd packages/client
uv run pytest tests/test_subscribe.py
```

## Description

Runs the client service test suite, which includes:
- Client agent tests (`test_agent_api.py`, `test_agent_kasmvnc.py`)
- GPU health check tests (`test_check_gpu.py`)
- Liveness heartbeat tests (`test_heartbeat.py`)
- Status update tests (`test_update_inuse.py`)
- HTTP helper tests (`test_http_utils.py`)
- Logging configuration tests (`test_logging_setup.py`)
- Monitoring agent tests (`test_monitoring_config.py`, `tests/monitoring/`)
- Startup script tests (`test_start_sh_status.py`)
- Import validation tests (`test_imports.py`)

## Expected Output

```
============================= test session starts ==============================
collected 139 items

tests/test_agent_api.py ...........                                      [  7%]
tests/test_check_gpu.py ..............                                   [ 17%]
tests/test_heartbeat.py .............                                    [ 27%]
tests/test_logging_setup.py ......                                       [ 31%]
tests/test_update_inuse.py .........                                     [ 38%]
...
============================== 139 passed in 0.9s ==============================
```

## Common Test Options

```bash
# Run with coverage
uv run pytest --cov=lablink_client --cov-report=term-missing

# Run specific test by name
uv run pytest -k test_gpu_check

# Stop on first failure
uv run pytest -x

# Show local variables on failure
uv run pytest -l

# Run only failed tests from last run
uv run pytest --lf
```

## Troubleshooting

### Import Errors
Using `uv run` automatically handles the Python path. If you see `ModuleNotFoundError`:
```bash
# Ensure you're in the package directory
cd packages/client

# Re-sync dependencies
uv sync --extra dev
```

### Missing Dependencies
Install dev dependencies:
```bash
uv sync --extra dev
```

### GPU Mock Errors
Tests mock GPU functionality. If you see CUDA-related errors, check that mocks in `conftest.py` are properly configured.

## CI Integration

These tests run automatically in `.github/workflows/ci.yml` on:
- Pull requests affecting `packages/client/**`
- Pushes to main/test branches

## Related Commands

- `/test-allocator` - Run allocator package tests
- `/test-coverage` - Run tests with coverage for both packages
- `/lint` - Run linting checks