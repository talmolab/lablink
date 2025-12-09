# Run Allocator Unit Tests

Run unit tests for the allocator package using pytest.

## Command

```bash
cd packages/allocator
uv run pytest tests --ignore=tests/terraform
```

**Note**: Terraform tests are ignored by default because they require an S3 backend configuration. See `/validate-terraform` for running Terraform tests in CI or with proper AWS credentials.

## With Verbose Output

```bash
cd packages/allocator
uv run pytest tests --ignore=tests/terraform -v
```

## Run Specific Test File

```bash
cd packages/allocator
uv run pytest tests/test_api_calls.py
```

## Run All Tests (Including Terraform)

For CI or when you have AWS credentials configured:

```bash
cd packages/allocator
uv run pytest tests
```

**Warning**: Terraform tests require AWS credentials and will fail locally without proper S3 backend configuration.

## Description

Runs the allocator service test suite, which includes:
- API endpoint tests (`test_api_calls.py`)
- Database operation tests (`test_database.py`)
- Admin authentication tests (`test_admin_auth.py`)
- Configuration validation tests (`test_validate_config.py`)
- DNS and SSL configuration tests

Terraform tests (`tests/terraform/`) are run separately in CI with proper AWS credentials.

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
uv run pytest tests --ignore=tests/terraform --cov=lablink_allocator --cov-report=term-missing

# Run specific test by name
uv run pytest tests --ignore=tests/terraform -k test_request_vm

# Stop on first failure
uv run pytest tests --ignore=tests/terraform -x

# Show local variables on failure
uv run pytest tests --ignore=tests/terraform -l

# Run only failed tests from last run
uv run pytest tests --ignore=tests/terraform --lf
```

## Troubleshooting

### Import Errors
Using `uv run` automatically handles the Python path. If you see `ModuleNotFoundError`:
```bash
# Ensure you're in the package directory
cd packages/allocator

# Re-sync dependencies
uv sync --extra dev
```

### Missing Dependencies
Install dev dependencies:
```bash
uv sync --extra dev
```

### Database Connection Errors
Tests use mocked database connections. If you see connection errors, check that fixtures in `conftest.py` are properly configured.

### Terraform Test Failures
Terraform tests require S3 backend configuration and AWS credentials. For local development, ignore them:
```bash
uv run pytest tests --ignore=tests/terraform
```

In CI, Terraform tests run with proper AWS OIDC credentials.

## CI Integration

These tests run automatically in `.github/workflows/ci.yml` on:
- Pull requests affecting `packages/allocator/**`
- Pushes to main/test branches

## Related Commands

- `/test-client` - Run client package tests
- `/test-coverage` - Run tests with coverage for both packages
- `/lint` - Run linting checks