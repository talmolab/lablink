---
name: pr
description: >
  Create a well-structured GitHub PR with proper branching, testing, formatting, and documentation.
  Use when the user says "create a PR", "make a PR", "open a pull request", or wants to submit
  changes for review. Handles the full workflow: branch creation, implementation, testing,
  formatting, committing, and PR creation with comprehensive descriptions.
---

# Create a GitHub Pull Request

## Overview

This skill guides the complete PR workflow from branch creation to PR submission for the LabLink project.

## Step 1: Branch Setup

### Pull latest main
```bash
git checkout main
git pull origin main
```

### Create feature branch
Use a descriptive branch name following the pattern: `{user}/{type}-{description}`

Types:
- `feat` or `feature` - New functionality
- `fix` - Bug fixes
- `refactor` - Code restructuring
- `docs` - Documentation updates
- `test` - Test additions/improvements
- `chore` - Maintenance tasks

```bash
git checkout -b andrew/feat-descriptive-name
```

## Step 2: Understand the Problem

Before coding, clearly identify:
1. **Core problem**: What issue are we solving?
2. **Scope**: What files/modules will be affected?
3. **Approach**: What's the implementation strategy?
4. **Edge cases**: What scenarios need special handling?

If there's an associated GitHub issue, fetch it for context:
```bash
gh issue view <issue-number>
```

## Step 3: Implement Changes

- Make focused, incremental changes
- Follow existing code patterns and style (see `openspec/project.md`)
- Add type hints for public functions
- Use Google-style docstrings
- Consider backwards compatibility

## Step 4: Write Tests

### Location
Tests go in the `tests/` directory within each package:
- `packages/allocator/tests/`
- `packages/client/tests/`

### Requirements
- Cover all new functionality
- Test edge cases and error conditions
- Test both success and failure paths
- Minimum 90% coverage (enforced in CI)

### Test file naming
- `test_{module_name}.py` for module tests

## Step 5: Lint and Format

Run linting checks:
```bash
# Check linting
ruff check packages/allocator packages/client

# Auto-fix lint issues
ruff check --fix packages/allocator packages/client
```

## Step 6: Run Tests

Run tests per package:
```bash
# Allocator tests
cd packages/allocator && PYTHONPATH=. pytest

# Client tests
cd packages/client && PYTHONPATH=. pytest

# With coverage
cd packages/allocator && PYTHONPATH=. pytest --cov
cd packages/client && PYTHONPATH=. pytest --cov
```

## Step 7: Commit Changes

### Commit structure
Make well-structured, atomic commits:
- Each commit should be a logical unit of work
- Write clear, descriptive commit messages
- Use conventional commit format

### Commit message format
```
<type>: <short description>

<optional longer description>

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

## Step 8: Push to GitHub

```bash
git push -u origin <branch-name>
```

## Step 9: Create Pull Request

### Create the PR
```bash
gh pr create --base main --title "<descriptive title>" --body "$(cat <<'EOF'
## Summary
<1-3 bullet points describing the changes>

## Changes Made
- <detailed list of changes>

## Testing
- <describe test coverage>
- <note any manual testing done>

## Design Decisions
- <explain key architectural choices>
- <note trade-offs considered>

## Related Issues
Closes #<issue-number> (if applicable)

---
🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

### If updating an existing PR

Fetch current PR description:
```bash
gh pr view <pr-number> --json body -q '.body'
```

Update PR description:
```bash
gh pr edit <pr-number> --body "<new body>"
```

### Fetch associated issue for context
If an issue is linked:
```bash
gh issue view <issue-number>
```

Use issue context to ensure PR description addresses all requirements.

## PR Description Checklist

- [ ] Summary clearly explains the "what" and "why"
- [ ] All significant changes are documented
- [ ] Breaking changes highlighted
- [ ] Test coverage described
- [ ] Design decisions explained with reasoning
- [ ] Related issues linked

## Quick Reference Commands

```bash
# Branch setup
git checkout main && git pull origin main
git checkout -b andrew/feat-my-feature

# Lint
ruff check packages/allocator packages/client
ruff check --fix packages/allocator packages/client

# Test
cd packages/allocator && PYTHONPATH=. pytest
cd packages/client && PYTHONPATH=. pytest

# Find changed files
git diff --name-only $(git merge-base origin/main HEAD)

# Commit
git add <files>
git commit -m "feat: description"

# Push and create PR
git push -u origin <branch>
gh pr create --base main --title "Title" --body "Description"

# View/edit existing PR
gh pr view <number>
gh pr edit <number> --body "New description"

# View linked issue
gh issue view <number>
```

## CI Checks

PRs trigger the following CI checks:
- **Lint**: `ruff check` on both packages
- **Tests**: `pytest` with coverage on both packages
- **Docker build**: Verify dev images build and run correctly
- **Terraform**: Validate client VM Terraform plans

Ensure all checks pass before requesting review.
