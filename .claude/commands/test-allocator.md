# Run Allocator Unit Tests

Run unit tests for the allocator package using pytest.

## Command

```bash
cd packages/allocator
PYTHONPATH=. pytest
```

## With Verbose Output

```bash
cd packages/allocator
PYTHONPATH=. pytest -v
```

## Run Specific Test File

```bash
cd packages/allocator
PYTHONPATH=. pytest tests/test_api_calls.py
```

## Description

Runs the allocator service test suite, which includes:
- API endpoint tests (`test_api_calls.py`)
- Database operation tests (`test_database.py`)
- Admin authentication tests (`test_admin_auth.py`)
- Terraform integration tests (`test_terraform_api.py`)
- Configuration validation tests (`test_validate_config.py`)
- DNS and SSL configuration tests

## Expected Output

```
============================= test session starts ==============================
collected 45 items

tests/test_api_calls.py ..................                               [ 40%]
tests/test_database.py ..............                                    [ 71%]
tests/test_admin_auth.py .....                                          [ 82%]
tests/test_terraform_api.py .....                                       [ 93%]
tests/test_validate_config.py ...                                       [100%]

============================== 45 passed in 5.2s ===============================
```

## Common Test Options

```bash
# Run with coverage
PYTHONPATH=. pytest --cov=lablink_allocator --cov-report=term-missing

# Run specific test by name
PYTHONPATH=. pytest -k test_request_vm

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

### Database Connection Errors
Tests use mocked database connections. If you see connection errors, check that fixtures in `conftest.py` are properly configured.

## CI Integration

These tests run automatically in `.github/workflows/ci.yml` on:
- Pull requests affecting `packages/allocator/**`
- Pushes to main/test branches

## Related Commands

- `/test-client` - Run client package tests
- `/test-coverage` - Run tests with coverage for both packages
- `/lint` - Run linting checks