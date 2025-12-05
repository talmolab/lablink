# Review GitHub Pull Request

Comprehensively review a GitHub Pull Request with planning mode and structured analysis.

## Command Template

```
Review PR #<NUMBER> using planning mode.

Steps:
1. Fetch PR details and all comments
2. Analyze code changes thoroughly
3. Post comprehensive review via gh CLI
```

## Usage

```bash
# Get PR number
gh pr list

# Then invoke this command and Claude will:
# - Use planning mode for structured analysis
# - Read all existing PR comments and reviews
# - Analyze code changes for correctness, style, and best practices
# - Post review feedback via gh CLI
```

## What This Command Does

### 1. Fetch PR Information

```bash
# View PR with all comments
gh pr view <PR_NUMBER> --comments

# Get inline code review comments
gh api repos/talmolab/lablink/pulls/<PR_NUMBER>/comments \
  --jq '.[] | {path: .path, line: .line, body: .body}'

# Get review summaries
gh api repos/talmolab/lablink/pulls/<PR_NUMBER>/reviews \
  --jq '.[].body'

# Get PR diff
gh pr diff <PR_NUMBER>
```

### 2. Analysis with Planning Mode

The review uses planning mode to systematically analyze:

**Review categories:**
- **Correctness**: Logic errors, bugs, edge cases
- **Code quality**: Readability, maintainability, documentation
- **Best practices**: PEP 8, type hints, docstrings, project conventions
- **Testing**: Test coverage, test quality, edge cases
- **Security**: Input validation, secrets, vulnerabilities
- **Performance**: Inefficiencies, optimization opportunities

### 3. Post Review via gh CLI

```bash
# Post review comment
gh pr review <PR_NUMBER> --comment --body "$(cat <<'EOF'
## Code Review

### Summary
[High-level overview of changes and assessment]

### Strengths
- Well-structured implementation
- Comprehensive tests included
- Clear documentation

### Issues Found

#### Critical
- [Issue description with file:line reference]

#### Important
- [Issue description with file:line reference]

#### Minor/Suggestions
- [Suggestion with rationale]

### Recommendations
1. [Action item]
2. [Action item]

### Questions
- [Clarification needed]
EOF
)"

# Or approve PR
gh pr review <PR_NUMBER> --approve --body "LGTM! ..."

# Or request changes
gh pr review <PR_NUMBER> --request-changes --body "Please address: ..."
```

## Example Workflow

### Step 1: List PRs
```bash
gh pr list
```

Output:
```
#42  feat: Add Claude dev commands   feat/add-dev-commands
#35  fix: Database connection issue  fix/db-connection
```

### Step 2: Review PR in Claude
Invoke this command and tell Claude:

```
Review PR #42 using planning mode
```

### Step 3: Claude's Analysis Process

Claude will:
1. **Fetch all data**:
   - PR description and metadata
   - All existing comments and reviews
   - Full code diff
   - Related files for context

2. **Plan the review**:
   - Identify files to review
   - Prioritize critical vs minor issues
   - Structure feedback categories

3. **Analyze thoroughly**:
   - Trace code logic
   - Identify edge cases
   - Check against project conventions (CLAUDE.md, openspec/project.md)
   - Verify test coverage

4. **Post structured review**:
   - Clear categorization of issues
   - File:line references for each issue
   - Actionable recommendations
   - Overall assessment

## Review Checklist

The command ensures these are checked:

### Code Correctness
- [ ] Logic errors or bugs
- [ ] Edge cases handled
- [ ] Error handling present
- [ ] Input validation

### Code Quality
- [ ] Follows PEP 8 (checked by ruff)
- [ ] Type hints for public functions
- [ ] Google-style docstrings
- [ ] Clear variable/function names
- [ ] No code duplication

### Python-Specific
- [ ] Proper use of type hints
- [ ] f-strings for formatting
- [ ] Context managers for resources
- [ ] Error messages informative
- [ ] Logging used appropriately

### Testing
- [ ] Tests added for new functionality
- [ ] Tests cover edge cases
- [ ] Tests are clear and maintainable
- [ ] Coverage meets 90% threshold
- [ ] Mocking used appropriately

### Documentation
- [ ] CLAUDE.md updated if needed
- [ ] README updated if needed
- [ ] CHANGELOG entry added
- [ ] Docstrings for public functions
- [ ] Comments for complex logic

### Project-Specific
- [ ] Follows openspec/project.md conventions
- [ ] OpenSpec change proposal created if needed
- [ ] CI workflows pass
- [ ] Docker builds succeed
- [ ] No secrets committed

## Addressing Review Comments

After Claude posts review:

### For PR Author

```bash
# View review comments
gh pr view <PR_NUMBER> --comments

# Make fixes based on feedback
# ... edit files ...

# Commit and push
git add .
git commit -m "fix: Address review feedback"
git push

# Reply to review
gh pr comment <PR_NUMBER> --body "Addressed all feedback:
- Fixed validation logic in src/lablink_allocator/main.py:45
- Added tests for edge cases
- Updated documentation
"
```

### For Reviewer (Follow-up)

```bash
# Check if issues addressed
gh pr diff <PR_NUMBER>

# Post follow-up review
gh pr review <PR_NUMBER> --comment --body "Thanks for the fixes! LGTM now."

# Or approve
gh pr review <PR_NUMBER> --approve --body "All feedback addressed. Approving!"
```

## Advanced Options

### Review Specific Files Only

Tell Claude:
```
Review PR #42, focusing only on changes to packages/allocator/src/**
```

### Review for Specific Concerns

Tell Claude:
```
Review PR #42 for security vulnerabilities and input validation
```

### Compare Against Standards

Tell Claude:
```
Review PR #42 and check compliance with openspec/project.md conventions
```

## gh CLI Setup

If gh CLI not installed:

```bash
# Windows (use winget or choco)
winget install GitHub.cli
# or
choco install gh

# macOS
brew install gh

# Linux (Ubuntu/Debian)
sudo apt install gh

# Authenticate
gh auth login
```

## Related Commands

- `/pr-description` - Generate PR descriptions
- `/update-changelog` - Update CHANGELOG based on PR