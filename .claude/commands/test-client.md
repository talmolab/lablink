# Run Client Unit Tests

Run unit tests for the client package using pytest.

## Command

```bash
cd packages/client
PYTHONPATH=. pytest
```

## With Verbose Output

```bash
cd packages/client
PYTHONPATH=. pytest -v
```

## Run Specific Test File

```bash
cd packages/client
PYTHONPATH=. pytest tests/test_subscribe.py
```

## Description

Runs the client service test suite, which includes:
- Subscription service tests (`test_subscribe.py`)
- GPU health check tests (`test_check_gpu.py`)
- Status update tests (`test_update_inuse.py`)
- Logger configuration tests (`test_logger_config.py`, `test_logger_utils.py`)
- CRD connection tests (`test_connect_crd.py`)
- Import validation tests (`test_imports.py`)

## Expected Output

```
============================= test session starts ==============================
collected 28 items

tests/test_subscribe.py ......                                           [ 21%]
tests/test_check_gpu.py .......                                          [ 46%]
tests/test_update_inuse.py .....                                        [ 64%]
tests/test_logger_config.py ..                                          [ 71%]
tests/test_logger_utils.py .....                                        [ 89%]
tests/test_connect_crd.py ...                                           [100%]

============================== 28 passed in 3.8s ===============================
```

## Common Test Options

```bash
# Run with coverage
PYTHONPATH=. pytest --cov=lablink_client --cov-report=term-missing

# Run specific test by name
PYTHONPATH=. pytest -k test_gpu_check

# Stop on first failure
PYTHONPATH=. pytest -x

# Show local variables on failure
PYTHONPATH=. pytest -l

# Run only failed tests from last run
PYTHONPATH=. pytest --lf
```

## Troubleshooting

### Import Errors
If you see `ModuleNotFoundError`, ensure `PYTHONPATH=.` is set:
```bash
export PYTHONPATH=.  # Unix/Mac
set PYTHONPATH=.     # Windows CMD
$env:PYTHONPATH="."  # Windows PowerShell
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