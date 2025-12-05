# Generate Pull Request Description

Generate a comprehensive PR description based on git commits and code changes.

## Command Template

```
Generate a PR description for the current branch based on git history and diff against main
```

## What This Command Does

Claude will:
1. Analyze `git diff main...HEAD` to see all changes
2. Review commit messages since branch divergence
3. Identify changed files and their purposes
4. Generate structured PR description
5. Format output as markdown ready for GitHub

## Manual Process

If you prefer to generate manually:

```bash
# View commits since branching from main
git log --oneline main..HEAD

# View full diff
git diff main...HEAD

# View changed files summary
git diff --stat main...HEAD

# View commit messages with details
git log --pretty=format:"%h - %s%n%b" main..HEAD
```

## PR Description Template

Claude will generate something like:

```markdown
## Summary

[1-2 sentence overview of what this PR does]

## Changes

### Added
- New feature X in `packages/allocator/src/lablink_allocator/file.py`
- New endpoint for Y in `main.py`
- Tests for Z in `tests/test_feature.py`

### Changed
- Updated function A to handle edge case B
- Improved performance of C by implementing caching

### Fixed
- Corrected database connection handling in `database.py:45`
- Fixed Terraform validation error in client VM creation

## Technical Details

[Brief explanation of implementation approach, key decisions, or algorithms used]

## Testing

- [ ] Allocator unit tests pass (`cd packages/allocator && PYTHONPATH=. pytest`)
- [ ] Client unit tests pass (`cd packages/client && PYTHONPATH=. pytest`)
- [ ] Coverage meets 90% threshold
- [ ] Docker images build successfully
- [ ] Tested locally with [describe test scenario]
- [ ] CI workflows pass

## Related Issues

Closes #[issue-number] (if applicable)
Related to #[issue-number] (if applicable)

## Checklist

- [ ] Code follows project conventions (PEP 8, type hints, docstrings)
- [ ] Documentation updated (CLAUDE.md, docs/)
- [ ] CHANGELOG.md updated
- [ ] Tests added/updated
- [ ] No breaking changes (or breaking changes documented)
- [ ] OpenSpec change proposal created (if applicable)

## Screenshots/Output

[If applicable, include example output, logs, or terminal output]
```

## Example Usage

### Step 1: Create feature branch
```bash
git checkout -b feat/add-https-support
# ... make changes ...
git add .
git commit -m "feat: Add HTTPS support to client services"
git push origin feat/add-https-support
```

### Step 2: Generate PR description
Invoke this command in Claude Code, and Claude will analyze your branch and generate the description.

### Step 3: Create PR with generated description
```bash
# Create PR with gh CLI
gh pr create --title "Add HTTPS support to client services" \
  --body-file pr_description.md

# Or copy-paste description into GitHub web interface
```

## Customizing the Description

### For Different PR Types

**Feature PRs:**
```
Generate a PR description for this feature branch, highlighting:
- New capabilities added
- User benefits
- Example usage
```

**Bug Fix PRs:**
```
Generate a PR description for this bug fix, including:
- Description of the bug
- Root cause analysis
- Fix implementation
- Test coverage
```

**Refactoring PRs:**
```
Generate a PR description for this refactoring, explaining:
- Why the refactoring was needed
- What was changed
- Performance/maintainability improvements
```

**Documentation PRs:**
```
Generate a PR description for documentation updates, summarizing:
- What documentation was added/updated
- Why it was needed
- Sections affected
```

## Best Practices for PR Descriptions

### Be Specific
```
Bad:  "Fixed bug"
Good: "Fixed database connection timeout in allocator service causing VM creation to fail"

Bad:  "Updated tests"
Good: "Added edge case tests for GPU health checks with CUDA unavailable scenarios"
```

### Include Context
- Why the change was needed
- What problem it solves
- Any alternatives considered

### Reference Issues
```markdown
Closes #42
Fixes #38
Related to #35
```

### Show Evidence
- Test results
- Before/after comparisons
- Performance metrics
- Example output

## PR Description Checklist

Ensure description includes:

- [ ] Clear summary of changes
- [ ] Why changes were made
- [ ] How to test the changes
- [ ] Breaking changes (if any)
- [ ] Related issues/PRs
- [ ] Testing checklist
- [ ] Screenshots/output (if applicable)

## Updating PR Description

If description needs updates:

```bash
# Update PR description
gh pr edit <PR_NUMBER> --body "Updated description..."

# Or append to existing description
CURRENT=$(gh pr view <PR_NUMBER> --json body -q .body)
gh pr edit <PR_NUMBER> --body "$CURRENT

## Update
[Additional information]
"
```

## For OpenSpec Changes

If PR implements an OpenSpec change:

```markdown
## OpenSpec Change

This PR implements OpenSpec change: `add-claude-dev-commands`

**Proposal**: openspec/changes/add-claude-dev-commands/proposal.md
**Tasks**: openspec/changes/add-claude-dev-commands/tasks.md

### Implementation Status

- [x] Task 1.1: Create .claude/commands directory
- [x] Task 2.1: Create testing commands
- [ ] Task 3.1: Create Docker commands (in progress)

See proposal for full details.
```

## Related Commands

- `/review-pr` - Review a PR
- `/update-changelog` - Update CHANGELOG for the PR