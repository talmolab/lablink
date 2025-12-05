# Development Environment Setup

Set up your local development environment for LabLink development.

## Quick Setup

```bash
# 1. Install uv (if not already installed)
# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Clone repository
git clone https://github.com/talmolab/lablink.git
cd lablink

# 3. Set up allocator package
cd packages/allocator
uv sync --extra dev
cd ../..

# 4. Set up client package
cd packages/client
uv sync --extra dev
cd ../..

# 5. Verify setup
cd packages/allocator && PYTHONPATH=. pytest
cd ../client && PYTHONPATH=. pytest
```

## Detailed Setup Steps

### 1. Prerequisites

Install required tools:

```bash
# Git (if not installed)
# Windows: https://git-scm.com/download/win
# macOS: brew install git
# Linux: sudo apt install git

# Python 3.9+ (if not installed)
# Windows: https://www.python.org/downloads/
# macOS: brew install python@3.11
# Linux: sudo apt install python3.11

# Docker (for container testing)
# Download from: https://www.docker.com/products/docker-desktop

# GitHub CLI (for PR/workflow commands)
# Windows: winget install GitHub.cli
# macOS: brew install gh
# Linux: sudo apt install gh
```

### 2. Clone Repository

```bash
# HTTPS
git clone https://github.com/talmolab/lablink.git
cd lablink

# Or SSH (if you have SSH keys configured)
git clone git@github.com:talmolab/lablink.git
cd lablink
```

### 3. Install uv Package Manager

```bash
# Windows (PowerShell)
irm https://astral.sh/uv/install.ps1 | iex

# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Verify installation
uv --version
```

### 4. Set Up Allocator Package

```bash
cd packages/allocator

# Install dependencies with dev tools
uv sync --extra dev

# Verify installation
uv run pytest --version
uv run ruff --version

# Run tests to verify setup
PYTHONPATH=. uv run pytest
```

### 5. Set Up Client Package

```bash
cd packages/client

# Install dependencies with dev tools
uv sync --extra dev

# Verify installation
uv run pytest --version
uv run ruff --version

# Run tests to verify setup
PYTHONPATH=. uv run pytest
```

### 6. Set Up Documentation (Optional)

```bash
# From repository root
uv venv .venv-docs
source .venv-docs/bin/activate  # Unix/Mac
# .venv-docs\Scripts\activate  # Windows

uv sync --extra docs

# Verify docs build
mkdocs build
```

### 7. Authenticate with GitHub (Optional)

```bash
# Required for /trigger-ci, /review-pr, etc.
gh auth login

# Verify authentication
gh auth status
```

## Verify Complete Setup

Run all verification checks:

```bash
# 1. Check uv installation
uv --version

# 2. Check Python version
python --version  # Should be 3.9+

# 3. Allocator tests
cd packages/allocator
PYTHONPATH=. pytest
echo "✓ Allocator tests passed"

# 4. Client tests
cd ../client
PYTHONPATH=. pytest
echo "✓ Client tests passed"

# 5. Linting
cd ../..
ruff check packages/allocator packages/client
echo "✓ Linting passed"

# 6. Docker (optional)
docker --version
echo "✓ Docker installed"

# 7. GitHub CLI (optional)
gh --version
echo "✓ GitHub CLI installed"
```

## IDE Setup

### Visual Studio Code

Recommended extensions:
- **Python** (ms-python.python)
- **Ruff** (charliermarsh.ruff)
- **Markdown All in One** (yzhang.markdown-all-in-one)
- **Docker** (ms-azuretools.vscode-docker)

Settings (`.vscode/settings.json`):
```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/packages/allocator/.venv/bin/python",
  "python.testing.pytestEnabled": true,
  "python.linting.ruffEnabled": true,
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.fixAll": true
  }
}
```

### PyCharm

1. Open project: `File → Open → lablink/`
2. Configure interpreters:
   - Allocator: `packages/allocator/.venv`
   - Client: `packages/client/.venv`
3. Enable pytest: `Settings → Tools → Python Integrated Tools → Testing → pytest`
4. Enable ruff: `Settings → Tools → External Tools → Add ruff`

## Common Development Tasks

### Running Tests

```bash
# All allocator tests
cd packages/allocator && PYTHONPATH=. pytest

# All client tests
cd packages/client && PYTHONPATH=. pytest

# With coverage
PYTHONPATH=. pytest --cov
```

### Linting and Formatting

```bash
# Check both packages
ruff check packages/allocator packages/client

# Auto-fix
ruff check --fix packages/allocator packages/client
ruff format packages/allocator packages/client
```

### Building Docker Images

```bash
# Allocator dev image
docker build -t lablink-allocator:dev -f packages/allocator/Dockerfile.dev .

# Client dev image
docker build -t lablink-client:dev -f packages/client/Dockerfile.dev .
```

### Serving Documentation

```bash
uv run --extra docs mkdocs serve
# Open http://localhost:8000
```

## Troubleshooting Setup

### uv Not Found After Installation
**Symptom**: `uv: command not found`

**Solutions**:
```bash
# Add uv to PATH
# Windows: Restart PowerShell
# Unix/Mac: Run 'source ~/.bashrc' or restart terminal

# Or use full path
~/.cargo/bin/uv --version
```

### Python Version Mismatch
**Symptom**: `requires-python = ">=3.9"` error

**Solutions**:
```bash
# Check Python version
python --version

# Install Python 3.9+ if needed
# Then recreate virtual environments
uv sync --extra dev
```

### Import Errors in Tests
**Symptom**: `ModuleNotFoundError` when running tests

**Solutions**:
```bash
# Ensure PYTHONPATH is set
export PYTHONPATH=.  # Unix/Mac
set PYTHONPATH=.     # Windows CMD
$env:PYTHONPATH="."  # Windows PowerShell

# Or use uv run
uv run pytest
```

### Docker Build Fails
**Symptom**: Docker build errors

**Solutions**:
1. Ensure Docker Desktop is running
2. Verify internet connection (for base image download)
3. Check disk space: `docker system df`
4. Clean up if needed: `docker system prune`

## Next Steps

After setup:
1. **Read CLAUDE.md**: Familiarize yourself with project structure
2. **Explore slash commands**: Try `/test-allocator`, `/lint`, etc.
3. **Run local allocator**: See `/run-allocator-local`
4. **Create a branch**: `git checkout -b feat/your-feature`
5. **Make changes**: Edit code, add tests, update docs
6. **Open a PR**: Use `/pr-description` to generate description

## Related Commands

- `/test-allocator` - Run allocator tests
- `/test-client` - Run client tests
- `/lint` - Check code quality
- `/docs-serve` - Preview documentation
- `/run-allocator-local` - Run allocator service locally