# Run Tests with Coverage

Run unit tests with coverage analysis for both allocator and client packages.

## Quick Command

```bash
# Run both packages with coverage
cd packages/allocator && PYTHONPATH=. pytest --cov=lablink_allocator --cov-report=term-missing && \
cd ../client && PYTHONPATH=. pytest --cov=lablink_client --cov-report=term-missing
```

## Individual Package Coverage

### Allocator Coverage

```bash
cd packages/allocator
PYTHONPATH=. pytest --cov=lablink_allocator --cov-report=term-missing
```

### Client Coverage

```bash
cd packages/client
PYTHONPATH=. pytest --cov=lablink_client --cov-report=term-missing
```

## With HTML Report

```bash
# Allocator
cd packages/allocator
PYTHONPATH=. pytest --cov=lablink_allocator --cov-report=html
# Open htmlcov/index.html in browser

# Client
cd packages/client
PYTHONPATH=. pytest --cov=lablink_client --cov-report=html
# Open htmlcov/index.html in browser
```

## Description

Runs pytest with coverage analysis to identify untested code. The `--cov-report=term-missing` flag shows which lines are not covered by tests.

### Coverage Targets
- **Minimum**: 90% coverage (enforced in CI)
- **Goal**: >95% for critical paths (API endpoints, database operations, Terraform)

## Expected Output

```
============================= test session starts ==============================
collected 45 items

tests/test_api_calls.py ..................                               [ 40%]
tests/test_database.py ..............                                    [ 71%]
...

---------- coverage: platform linux, python 3.11.0-final-0 -----------
Name                                    Stmts   Miss  Cover   Missing
---------------------------------------------------------------------
src/lablink_allocator/__init__.py          2      0   100%
src/lablink_allocator/main.py           145      8    94%   78-82, 156
src/lablink_allocator/database.py        89      2    98%   45, 89
src/lablink_allocator/get_config.py       24      0   100%
---------------------------------------------------------------------
TOTAL                                    260     10    96%

============================== 45 passed in 5.2s ===============================
```

## Coverage Report Formats

```bash
# Terminal with missing lines
pytest --cov=lablink_allocator --cov-report=term-missing

# HTML report (browsable)
pytest --cov=lablink_allocator --cov-report=html

# XML report (for CI tools)
pytest --cov=lablink_allocator --cov-report=xml

# Combined reports
pytest --cov=lablink_allocator --cov-report=term-missing --cov-report=html
```

## Focus on Specific Modules

```bash
# Only test coverage for main.py
cd packages/allocator
PYTHONPATH=. pytest --cov=lablink_allocator.main --cov-report=term-missing

# Only test coverage for database.py
PYTHONPATH=. pytest --cov=lablink_allocator.database --cov-report=term-missing
```

## Identify Uncovered Code

```bash
# Show only uncovered lines
cd packages/allocator
PYTHONPATH=. pytest --cov=lablink_allocator --cov-report=term-missing | grep "src/lablink"
```

## CI Integration

Coverage is checked automatically in `.github/workflows/ci.yml` with minimum threshold of 90%.

## Troubleshooting

### Low Coverage Warnings
If coverage is below 90%, CI will fail. Add tests for uncovered code paths:
1. Identify missing coverage from report
2. Write tests for uncovered lines
3. Re-run coverage to verify improvement

### Coverage Not Reflecting Tests
Ensure tests are actually running the code:
```bash
# Run with verbose output to see what's tested
PYTHONPATH=. pytest -v --cov=lablink_allocator
```

## Related Commands

- `/test-allocator` - Run allocator tests only
- `/test-client` - Run client tests only
- `/lint` - Run linting checks