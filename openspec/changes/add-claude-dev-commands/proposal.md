# Proposal: Add Claude Development Commands

## Why

Developers currently need to manually look up and execute common development tasks like running tests, building Docker images, linting code, creating PRs, and reviewing changes. This slows down development velocity and creates inconsistency in how tasks are performed. Adding Claude development slash commands will provide instant access to standardized development workflows, reducing friction and ensuring best practices are followed consistently.

## What Changes

This proposal adds a comprehensive set of Claude slash commands (`.claude/commands/*.md`) to streamline common development workflows:

### Testing & Validation Commands
- **`/test-allocator`**: Run allocator unit tests with pytest
- **`/test-client`**: Run client unit tests with pytest
- **`/test-coverage`**: Run tests with coverage analysis for both packages
- **`/lint`**: Run ruff linting on both packages
- **`/lint-fix`**: Auto-fix linting issues with ruff

### Docker Commands
- **`/docker-build-allocator`**: Build allocator Docker images (dev and prod)
- **`/docker-build-client`**: Build client Docker images (dev and prod)
- **`/docker-test-allocator`**: Run allocator Docker container tests
- **`/docker-test-client`**: Run client Docker container tests

### CI/CD Commands
- **`/trigger-ci`**: Manually trigger CI workflow
- **`/trigger-docker-build`**: Trigger Docker image build workflow
- **`/publish-allocator`**: Publish allocator package to PyPI
- **`/publish-client`**: Publish client package to PyPI

### Git & PR Commands
- **`/pr-description`**: Generate comprehensive PR description from git history
- **`/review-pr`**: Perform comprehensive PR review with planning mode
- **`/update-changelog`**: Update CHANGELOG.md based on recent changes

### Documentation Commands
- **`/docs-serve`**: Serve documentation locally with MkDocs
- **`/docs-build`**: Build documentation for deployment

### Development Workflow Commands
- **`/dev-setup`**: Set up local development environment
- **`/run-allocator-local`**: Run allocator service locally for testing
- **`/validate-terraform`**: Validate Terraform configurations

All commands will follow the established patterns from the GAPIT3 pipeline project, with LabLink-specific adaptations for the monorepo structure, Python/Flask stack, and Docker-based development workflow.

## Impact

### Affected Specs
- **New capability**: `developer-experience` (new spec to be created)

### Affected Code
- **New directory**: `.claude/commands/` with 16+ command files
- **No code changes**: This is purely documentation/tooling enhancement
- **Documentation**: `CLAUDE.md` updated to reference new commands

### Benefits
- **Faster onboarding**: New developers can discover common tasks via slash commands
- **Consistency**: Standardized commands ensure everyone follows the same workflows
- **Reduced errors**: Pre-validated command patterns reduce typos and mistakes
- **Better PR quality**: Structured review and description generation commands
- **Improved testing**: Easy access to test and coverage commands encourages testing

### Non-Breaking
This change is entirely additive and has no impact on existing code, infrastructure, or workflows.