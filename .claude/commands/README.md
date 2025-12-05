# Claude Development Commands

This directory contains Claude Code slash commands for common LabLink development tasks.

## Usage

In Claude Code, type `/<command-name>` to invoke a command. Claude will expand the command file and assist with the task.

## Available Commands

### Testing & Validation

| Command | Description |
|---------|-------------|
| `/test-allocator` | Run allocator unit tests with pytest |
| `/test-client` | Run client unit tests with pytest |
| `/test-coverage` | Run tests with coverage analysis for both packages |
| `/lint` | Run ruff linting checks on both packages |
| `/lint-fix` | Auto-fix linting issues with ruff |

### Docker

| Command | Description |
|---------|-------------|
| `/docker-build-allocator` | Build allocator Docker images (dev and prod) |
| `/docker-build-client` | Build client Docker images (dev and prod) |
| `/docker-test-allocator` | Run functional tests on allocator container |
| `/docker-test-client` | Run functional tests on client container |

### CI/CD

| Command | Description |
|---------|-------------|
| `/trigger-ci` | Manually trigger CI workflow |
| `/trigger-docker-build` | Trigger Docker image build workflow |
| `/publish-allocator` | Publish allocator package to PyPI |
| `/publish-client` | Publish client package to PyPI |

### Git & Pull Requests

| Command | Description |
|---------|-------------|
| `/pr-description` | Generate comprehensive PR description |
| `/review-pr` | Perform thorough PR review with planning mode |
| `/update-changelog` | Update CHANGELOG.md based on recent changes |

### Documentation

| Command | Description |
|---------|-------------|
| `/docs-serve` | Serve documentation locally with live reload |
| `/docs-build` | Build documentation for deployment verification |

### Development Workflow

| Command | Description |
|---------|-------------|
| `/dev-setup` | Set up local development environment |
| `/run-allocator-local` | Run allocator Flask app locally |
| `/validate-terraform` | Validate Terraform configurations |

## Quick Start

```bash
# Run allocator tests
/test-allocator

# Check code quality
/lint

# Build Docker image
/docker-build-allocator

# Create PR with good description
/pr-description
```

## Adding New Commands

1. Create a new `.md` file in this directory
2. Follow the structure of existing commands
3. Add to the table in this README
4. Test the command by invoking it in Claude Code