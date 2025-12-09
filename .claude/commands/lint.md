# Run Linting Checks

Run ruff linting checks on both packages to ensure code quality and style compliance.

## Quick Command

```bash
# Check both packages
uv run ruff check packages/allocator packages/client
```

## Individual Package Checks

```bash
# Allocator only
uv run ruff check packages/allocator

# Client only
uv run ruff check packages/client
```

## With Detailed Output

```bash
# Show all violations with context
uv run ruff check packages/allocator packages/client --output-format=full

# Show statistics
uv run ruff check packages/allocator packages/client --statistics
```

## Description

Runs ruff linting to check for:
- **PEP 8 compliance**: Code style violations
- **Import ordering**: Standard library → Third-party → Local
- **Unused imports and variables**: Dead code detection
- **Line length**: Maximum 88 characters (ruff default)
- **Common bugs**: Potential runtime errors
- **Type hints**: Missing or incorrect type annotations

## Expected Output

### Clean Code
```
All checks passed!
```

### With Violations
```
packages/allocator/src/lablink_allocator/main.py:45:1: F401 [*] `os` imported but unused
packages/allocator/src/lablink_allocator/main.py:78:80: E501 Line too long (92 > 88)
packages/client/src/lablink_client/subscribe.py:23:5: F841 [*] Local variable `result` is assigned to but never used
Found 3 errors.
[*] 2 fixable with the `--fix` option.
```

## Check Specific Files

```bash
# Check specific file
uv run ruff check packages/allocator/src/lablink_allocator/main.py

# Check specific directory
uv run ruff check packages/allocator/src/lablink_allocator/
```

## Ignore Specific Rules

```bash
# Ignore specific error code
uv run ruff check packages/allocator --ignore F401

# Ignore multiple codes
uv run ruff check packages/allocator --ignore F401,E501
```

## Configuration

Ruff is configured in each package's `pyproject.toml`:

```toml
[tool.ruff.lint]
select = ["E", "F", "I", "N", "W"]  # Error, pyflakes, isort, naming, warnings
ignore = ["E501"]  # Ignore specific rules

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["F401"]  # Ignore unused imports in tests
```

## CI Integration

Linting runs automatically in `.github/workflows/ci.yml` on all PRs. CI will fail if any violations are found.

## Troubleshooting

### Too Many Errors
Start by fixing auto-fixable issues:
```bash
uv run ruff check --fix packages/allocator packages/client
```

### False Positives
Add per-file ignores in `pyproject.toml`:
```toml
[tool.ruff.lint.per-file-ignores]
"src/lablink_allocator/main.py" = ["E501"]
```

Or use inline comments:
```python
result = long_function_call()  # noqa: E501
```

### Conflicting Rules
Check ruff configuration:
```bash
uv run ruff check --show-settings packages/allocator
```

## Related Commands

- `/lint-fix` - Auto-fix linting issues
- `/test-allocator` - Run allocator tests
- `/test-client` - Run client tests