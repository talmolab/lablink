# Auto-Fix Linting Issues

Automatically fix linting issues using ruff's auto-fix and formatting capabilities.

## Quick Command

```bash
# Fix and format both packages (run from each package directory)
cd packages/allocator && uv run ruff check --fix . && uv run ruff format .
cd packages/client && uv run ruff check --fix . && uv run ruff format .
```

## Step-by-Step

### Step 1: Auto-Fix Violations

```bash
# Fix auto-fixable issues
cd packages/allocator && uv run ruff check --fix .
cd packages/client && uv run ruff check --fix .
```

### Step 2: Format Code

```bash
# Format code (consistent spacing, line breaks, etc.)
cd packages/allocator && uv run ruff format .
cd packages/client && uv run ruff format .
```

## Individual Package Fix

```bash
# Allocator only
cd packages/allocator
uv run ruff check --fix .
uv run ruff format .

# Client only
cd packages/client
uv run ruff check --fix .
uv run ruff format .
```

## What Gets Fixed

### Auto-Fixable Issues (ruff check --fix)
- **Unused imports**: Removes unused import statements
- **Import sorting**: Reorders imports (stdlib → third-party → local)
- **Trailing whitespace**: Removes unnecessary whitespace
- **Missing blank lines**: Adds required blank lines
- **Quotes**: Normalizes string quotes
- **F-string conversion**: Converts `.format()` to f-strings

### Formatting (ruff format)
- **Line length**: Wraps lines exceeding 88 characters
- **Indentation**: Standardizes to 4 spaces
- **Spacing**: Consistent spacing around operators
- **Line breaks**: Optimal line breaking for readability
- **Trailing commas**: Adds trailing commas in multi-line structures

## Preview Changes Before Applying

```bash
# Show what would be fixed (dry run)
cd packages/allocator
uv run ruff check --fix --diff .

# Show formatting changes without applying
uv run ruff format --diff .
```

## Fix Specific Files

```bash
# Fix specific file (from package directory)
cd packages/allocator
uv run ruff check --fix src/lablink_allocator/main.py
uv run ruff format src/lablink_allocator/main.py

# Fix all Python files in directory
uv run ruff check --fix src/
uv run ruff format src/
```

## Unsafe Fixes

Some fixes are considered "unsafe" and require explicit opt-in:

```bash
# Include unsafe fixes
cd packages/allocator
uv run ruff check --fix --unsafe-fixes .
```

**Warning**: Unsafe fixes may change code behavior. Review changes carefully.

## Verify Fixes

After auto-fixing, verify no issues remain:

```bash
# Check for remaining violations
cd packages/allocator && uv run ruff check .
cd packages/client && uv run ruff check .

# Run tests to ensure fixes didn't break anything
cd packages/allocator && uv run pytest tests --ignore=tests/terraform
cd packages/client && uv run pytest
```

## Git Workflow

```bash
# Before committing
cd packages/allocator && uv run ruff check --fix . && uv run ruff format .
cd packages/client && uv run ruff check --fix . && uv run ruff format .

# Review changes
git diff

# Commit if satisfied
git add packages/
git commit -m "style: Auto-fix linting issues with ruff"
```

## Pre-Commit Hook

Consider adding a pre-commit hook to auto-fix on commit:

```bash
# .git/hooks/pre-commit
#!/bin/bash
cd packages/allocator && uv run ruff check --fix . && uv run ruff format .
cd packages/client && uv run ruff check --fix . && uv run ruff format .
git add -u
```

## Exclude Files from Formatting

Edit `pyproject.toml` to exclude specific files:

```toml
[tool.ruff]
exclude = [
    "migrations/",
    "generated/",
]
```

## Troubleshooting

### Changes Not Applied
Ensure you have write permissions and the files aren't read-only.

### Formatting Conflicts
If manual edits conflict with formatter, let the formatter win:
```bash
# Force format
cd packages/allocator && uv run ruff format .
```

### Unsafe Fixes Changed Behavior
Revert unsafe fixes:
```bash
git checkout -- packages/
# Then re-run without --unsafe-fixes
cd packages/allocator && uv run ruff check --fix .
cd packages/client && uv run ruff check --fix .
```

## Related Commands

- `/lint` - Check for linting issues without fixing
- `/test-coverage` - Run tests with coverage after fixing
