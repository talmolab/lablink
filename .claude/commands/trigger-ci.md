# Trigger CI Workflow

Manually trigger the continuous integration workflow to run tests and linting.

## Command

```bash
# Trigger CI workflow on current branch
gh workflow run ci.yml

# Trigger on specific branch
gh workflow run ci.yml --ref feature-branch-name
```

## What This Workflow Does

The `ci.yml` workflow runs:
1. **Lint**: `ruff check` on both packages
2. **Allocator Tests**: pytest with coverage
3. **Client Tests**: pytest with coverage
4. **Docker Build Test**: Verify allocator Dockerfile.dev builds correctly
5. **Terraform Tests**: Validate client VM Terraform configurations

## View Workflow Runs

```bash
# List recent workflow runs
gh run list --workflow=ci.yml

# Watch specific run
gh run watch

# View logs for specific run
gh run view <run-id> --log
```

## Check Workflow Status

```bash
# Check status of latest run
gh run list --workflow=ci.yml --limit 1

# View details of specific run
gh run view <run-id>
```

## When to Manually Trigger

### Testing Workflow Changes
If you've modified `.github/workflows/ci.yml`, trigger manually to test without creating a PR:

```bash
# Push workflow changes to branch
git push origin your-branch

# Trigger workflow on that branch
gh workflow run ci.yml --ref your-branch
```

### Re-running Failed Checks
If CI failed due to transient issues:

```bash
# Re-run latest failed workflow
gh run rerun <run-id>

# Re-run only failed jobs
gh run rerun <run-id> --failed
```

### Testing Infrastructure Changes
Test changes that might affect CI (dependency updates, test configurations):

```bash
gh workflow run ci.yml
```

## Automatic Triggers

The CI workflow runs automatically on:
- **Pull requests** affecting:
  - `packages/allocator/**`
  - `packages/client/**`
  - `.github/workflows/ci.yml`
- **Pushes to main/test branches**

## Expected Duration

- **Lint**: ~30 seconds
- **Allocator tests**: ~1-2 minutes
- **Client tests**: ~1-2 minutes
- **Docker build test**: ~3-5 minutes
- **Total**: ~5-10 minutes

## Troubleshooting

### Workflow Not Found
Ensure you're in the repository root:
```bash
cd c:\repos\lablink
gh workflow list
```

### Permission Denied
Authenticate with GitHub CLI:
```bash
gh auth login
```

### Workflow Fails Immediately
Check workflow syntax:
```bash
# Validate workflow file
cat .github/workflows/ci.yml
```

## Related Commands

- `/trigger-docker-build` - Trigger Docker image build workflow
- `/test-coverage` - Run tests locally before triggering CI
- `/lint` - Run linting locally before triggering CI