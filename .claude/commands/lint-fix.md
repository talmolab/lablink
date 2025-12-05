# Auto-Fix Linting Issues

Automatically fix linting issues using ruff's auto-fix and formatting capabilities.

## Quick Command

```bash
# Fix and format both packages
ruff check --fix packages/allocator packages/client
ruff format packages/allocator packages/client
```

## Step-by-Step

### Step 1: Auto-Fix Violations

```bash
# Fix auto-fixable issues
ruff check --fix packages/allocator packages/client
```

### Step 2: Format Code

```bash
# Format code (consistent spacing, line breaks, etc.)
ruff format packages/allocator packages/client
```

## Individual Package Fix

```bash
# Allocator only
ruff check --fix packages/allocator
ruff format packages/allocator

# Client only
ruff check --fix packages/client
ruff format packages/client
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
ruff check --fix --diff packages/allocator

# Show formatting changes without applying
ruff format --diff packages/allocator
```

## Fix Specific Files

```bash
# Fix specific file
ruff check --fix packages/allocator/src/lablink_allocator/main.py
ruff format packages/allocator/src/lablink_allocator/main.py

# Fix all Python files in directory
ruff check --fix packages/allocator/src/
ruff format packages/allocator/src/
```

## Unsafe Fixes

Some fixes are considered "unsafe" and require explicit opt-in:

```bash
# Include unsafe fixes
ruff check --fix --unsafe-fixes packages/allocator
```

**Warning**: Unsafe fixes may change code behavior. Review changes carefully.

## Verify Fixes

After auto-fixing, verify no issues remain:

```bash
# Check for remaining violations
ruff check packages/allocator packages/client

# Run tests to ensure fixes didn't break anything
cd packages/allocator && PYTHONPATH=. pytest
cd packages/client && PYTHONPATH=. pytest
```

## Git Workflow

```bash
# Before committing
ruff check --fix packages/allocator packages/client
ruff format packages/allocator packages/client

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
ruff check --fix packages/allocator packages/client
ruff format packages/allocator packages/client
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
ruff format packages/allocator
```

### Unsafe Fixes Changed Behavior
Revert unsafe fixes:
```bash
git checkout -- packages/
# Then re-run without --unsafe-fixes
ruff check --fix packages/allocator packages/client
```

## Related Commands

- `/lint` - Check for linting issues without fixing
- `/test-coverage` - Run tests with coverage after fixing
