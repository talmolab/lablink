# Contributing to LabLink

Thank you for your interest in contributing to LabLink! This guide will help you get started.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Contribution Workflow](#contribution-workflow)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Documentation](#documentation)
- [Pull Request Process](#pull-request-process)
- [Getting Help](#getting-help)

## Code of Conduct

This project adheres to a code of conduct that we expect all contributors to follow. Please be respectful and constructive in all interactions.

**Expected Behavior:**
- Be respectful and inclusive
- Welcome newcomers and help them learn
- Focus on what is best for the community
- Show empathy towards other community members

**Unacceptable Behavior:**
- Harassment, discrimination, or offensive comments
- Trolling or insulting/derogatory comments
- Public or private harassment
- Publishing others' private information without permission

## Getting Started

### Ways to Contribute

- 🐛 **Report bugs**: Open an issue describing the problem
- ✨ **Suggest features**: Open an issue with enhancement label
- 📝 **Improve documentation**: Fix typos, add examples, clarify instructions
- 🔧 **Fix bugs**: Submit pull requests for open issues
- 🚀 **Add features**: Implement new functionality
- 🧪 **Write tests**: Improve test coverage
- 💬 **Help others**: Answer questions in issues and discussions

### Before You Start

1. **Check existing issues**: Someone may already be working on it
2. **Open an issue first**: For major changes, discuss before implementing
3. **Read the docs**: Familiarize yourself with LabLink architecture
4. **Review CLAUDE.md**: Developer-focused project overview

## Development Setup

### Prerequisites

- Python 3.9 or higher
- Docker and Docker Desktop running
- AWS CLI (for testing infrastructure)
- Terraform 1.6.6+ (for testing infrastructure)
- Git

### Local Setup

```bash
# Fork and clone the repository
git clone https://github.com/YOUR_USERNAME/lablink.git
cd lablink

# Install uv (recommended Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Setup allocator service
cd lablink-allocator/lablink-allocator-service
uv sync --extra dev

# Setup client service
cd ../../lablink-client-base/lablink-client-service
uv sync --extra dev

# Return to root
cd ../..
```

### Verify Setup

```bash
# Run allocator tests
cd lablink-allocator/lablink-allocator-service
PYTHONPATH=. pytest

# Run client tests
cd ../../lablink-client-base/lablink-client-service
PYTHONPATH=. pytest

# Run linting
ruff check .

# Build Docker images
docker build -t lablink-allocator -f lablink-allocator/Dockerfile .
docker build -t lablink-client -f lablink-client-base/lablink-client-base-image/Dockerfile .
```

## How to Contribute

### Reporting Bugs

**Before reporting:**
1. Check if the bug has already been reported
2. Try to reproduce on the latest version
3. Check the [Troubleshooting Guide](https://talmolab.github.io/lablink/troubleshooting/)

**When reporting, include:**
- Clear, descriptive title
- Steps to reproduce the issue
- Expected behavior vs actual behavior
- Error messages and logs
- Environment details (OS, Python version, Docker version)
- Screenshots (if applicable)

**Example bug report:**

```markdown
**Title**: PostgreSQL connection fails after deployment

**Description**:
After deploying the allocator to AWS, cannot connect to PostgreSQL database.

**Steps to Reproduce**:
1. Deploy allocator with `terraform apply`
2. SSH into instance
3. Try to access database: `psql -U lablink -d lablink_db`

**Expected**: Successfully connect to database

**Actual**: Connection refused error

**Environment**:
- OS: Ubuntu 20.04
- Terraform: 1.6.6
- Image tag: linux-amd64-latest

**Logs**:
```
[error logs here]
```
```

### Suggesting Features

**Before suggesting:**
1. Check if it's already suggested or implemented
2. Consider if it fits the project scope
3. Think about backwards compatibility

**When suggesting, include:**
- Clear, descriptive title
- Use case and motivation
- Proposed solution
- Alternative solutions considered
- Impact on existing functionality

**Example feature request:**

```markdown
**Title**: Add support for Azure cloud provider

**Use Case**:
Some research institutions use Azure instead of AWS and would benefit from LabLink.

**Proposed Solution**:
- Add Azure provider to Terraform configurations
- Support Azure VMs alongside EC2
- Document Azure-specific setup

**Alternatives**:
- Create separate fork for Azure
- Use abstraction layer for multi-cloud support

**Impact**:
- Requires significant changes to infrastructure code
- Need Azure-specific configuration options
- May need separate documentation
```

## Contribution Workflow

### 1. Fork the Repository

Click "Fork" button on GitHub to create your copy.

### 2. Create a Branch

Use descriptive branch names:

```bash
git checkout -b feature/add-spot-instance-support
git checkout -b fix/postgresql-connection-issue
git checkout -b docs/improve-configuration-guide
```

**Branch naming conventions:**
- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation changes
- `refactor/` - Code refactoring
- `test/` - Test additions or modifications

### 3. Make Your Changes

Follow the [Coding Standards](#coding-standards) below.

### 4. Test Your Changes

```bash
# Run tests
PYTHONPATH=. pytest

# Run linting
ruff check .

# Auto-fix linting issues
ruff check --fix .

# Format code
ruff format .

# Run type checking (if applicable)
mypy .
```

### 5. Commit Your Changes

Use clear, descriptive commit messages following [Conventional Commits](https://www.conventionalcommits.org/):

```bash
# Format: <type>(<scope>): <description>

git commit -m "feat(allocator): add support for Spot Instances"
git commit -m "fix(database): resolve PostgreSQL connection timeout"
git commit -m "docs(security): add section on OIDC setup"
git commit -m "test(api): add tests for VM request endpoint"
```

**Commit types:**
- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation changes
- `style` - Code style changes (formatting, etc.)
- `refactor` - Code refactoring
- `test` - Adding or updating tests
- `chore` - Maintenance tasks

### 6. Push to Your Fork

```bash
git push origin feature/add-spot-instance-support
```

### 7. Open a Pull Request

1. Go to the original repository
2. Click "New Pull Request"
3. Select your fork and branch
4. Fill in the PR template (see below)

## Coding Standards

### Python Style

- Follow [PEP 8](https://pep8.org/) style guide
- Use `ruff` for linting and formatting
- Maximum line length: 88 characters (Black default)
- Use type hints for function parameters and return values
- Write docstrings for all public functions and classes

**Example:**

```python
def request_vm(email: str, crd_command: str) -> dict[str, str]:
    """Request a VM from the allocator.

    Args:
        email: User email address for VM assignment.
        crd_command: Command to execute on the VM.

    Returns:
        Dictionary containing VM details:
        - hostname: VM hostname
        - status: Current VM status
        - assigned_at: Assignment timestamp

    Raises:
        ValueError: If email format is invalid.
        RuntimeError: If no VMs are available.

    Example:
        >>> result = request_vm("user@example.com", "python train.py")
        >>> print(result['hostname'])
        i-0abc123def456
    """
    if not validate_email(email):
        raise ValueError(f"Invalid email format: {email}")

    vm = get_available_vm()
    if not vm:
        raise RuntimeError("No VMs available")

    return assign_vm(vm, email, crd_command)
```

### Terraform Style

- Use descriptive resource names
- Add comments for complex logic
- Tag all resources with `Name`, `Project`, `Environment`
- Use variables for configurable values
- Include outputs for important values

**Example:**

```hcl
resource "aws_instance" "lablink_allocator" {
  ami           = var.ami_id
  instance_type = var.instance_type

  tags = {
    Name        = "lablink-allocator-${var.environment}"
    Project     = "LabLink"
    Environment = var.environment
    ManagedBy   = "Terraform"
  }

  # Security group allowing HTTP and SSH
  vpc_security_group_ids = [aws_security_group.lablink.id]
}
```

### Documentation Style

- Use clear, concise language
- Include code examples
- Test all commands before documenting
- Use consistent terminology
- Link to related documentation

See [Contributing to Documentation](https://talmolab.github.io/lablink/contributing-docs/) for detailed guidelines.

## Testing

### Writing Tests

- Write tests for all new functionality
- Maintain or improve code coverage
- Use descriptive test names
- Test both success and failure cases
- Mock external dependencies (AWS, database)

**Example test:**

```python
import pytest
from unittest.mock import MagicMock, patch

def test_request_vm_success():
    """Test successful VM request."""
    mock_db = MagicMock()
    mock_db.get_available_vm.return_value = {
        'hostname': 'i-12345',
        'status': 'available'
    }

    result = request_vm("user@example.com", "echo test", db=mock_db)

    assert result['hostname'] == 'i-12345'
    assert result['status'] == 'in-use'
    mock_db.update_vm_status.assert_called_once()

def test_request_vm_no_vms_available():
    """Test VM request when no VMs available."""
    mock_db = MagicMock()
    mock_db.get_available_vm.return_value = None

    with pytest.raises(RuntimeError, match="No VMs available"):
        request_vm("user@example.com", "echo test", db=mock_db)
```

### Running Tests

```bash
# Run all tests
PYTHONPATH=. pytest

# Run specific test file
PYTHONPATH=. pytest tests/test_api_calls.py

# Run specific test
PYTHONPATH=. pytest tests/test_api_calls.py::test_request_vm_success

# Run with coverage
PYTHONPATH=. pytest --cov=lablink_allocator_service --cov-report=html

# View coverage report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

### Test Requirements

- All new features must have tests
- Bug fixes should include regression tests
- Tests must pass in CI before merging
- Aim for >80% code coverage

## Documentation

### Updating Documentation

When making changes that affect users:

1. **Update relevant docs** in `docs/` directory
2. **Update docstrings** for API changes
3. **Update README.md** if adding major features
4. **Update CLAUDE.md** if changing architecture
5. **Test documentation** locally with `mkdocs serve`

### Documentation Checklist

- [ ] Docstrings updated for changed functions
- [ ] Relevant documentation pages updated
- [ ] Examples provided for new features
- [ ] Links to related documentation added
- [ ] Tested all commands/examples
- [ ] Screenshots added (if UI changes)

### Building Documentation Locally

**Using uv (Recommended):**

```bash
# Quick test (creates temporary environment automatically)
uv run --extra docs mkdocs serve

# Or create persistent virtual environment
uv venv .venv-docs
# Windows
.venv-docs\Scripts\activate
# macOS/Linux
source .venv-docs/bin/activate

# Install dependencies
uv sync --extra docs

# Serve documentation
mkdocs serve

# Open http://localhost:8000

# Build static site
mkdocs build
```

**Using pip:**

```bash
# Install docs dependencies
pip install -e ".[docs]"

# Serve documentation
mkdocs serve

# Open http://localhost:8000

# Build static site
mkdocs build
```

## Pull Request Process

### PR Template

When opening a PR, include:

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix (non-breaking change fixing an issue)
- [ ] New feature (non-breaking change adding functionality)
- [ ] Breaking change (fix or feature causing existing functionality to change)
- [ ] Documentation update

## Related Issue
Fixes #(issue number)

## Changes Made
- Bullet list of changes
- Be specific

## Testing
- [ ] Tests added/updated
- [ ] All tests pass locally
- [ ] Documentation updated

## Screenshots (if applicable)
Add screenshots for UI changes

## Checklist
- [ ] Code follows project style guidelines
- [ ] Self-review completed
- [ ] Comments added for complex code
- [ ] Documentation updated
- [ ] No new warnings generated
- [ ] Tests added and passing
- [ ] Branch is up to date with main
```

### PR Review Process

1. **Automated checks** run (CI tests, linting)
2. **Maintainer review** for code quality and design
3. **Address feedback** by pushing new commits
4. **Approval** from at least one maintainer
5. **Merge** by maintainer (squash merge preferred)

### PR Guidelines

**Do:**
- Keep PRs focused on a single concern
- Write clear PR descriptions
- Respond to feedback promptly
- Keep PRs up to date with main branch
- Be respectful of reviewers' time

**Don't:**
- Mix multiple unrelated changes
- Submit huge PRs (>500 lines if possible)
- Make breaking changes without discussion
- Merge without approval
- Force push after review starts

## Release Process

Maintainers follow this process for releases:

1. **Version bump** following semantic versioning
2. **Update CHANGELOG.md**
3. **Create release tag**: `git tag -a v1.1.0 -m "Release v1.1.0"`
4. **Push tag**: `git push origin v1.1.0`
5. **GitHub Release** created automatically
6. **Documentation** deployed with version

## Getting Help

### Resources

- 📖 **Documentation**: https://talmolab.github.io/lablink/
- 🐛 **Issues**: https://github.com/talmolab/lablink/issues
- 💬 **Discussions**: https://github.com/talmolab/lablink/discussions
- 📧 **Developer Guide**: [CLAUDE.md](CLAUDE.md)

### Questions?

- Check [FAQ](https://talmolab.github.io/lablink/faq/)
- Search [existing issues](https://github.com/talmolab/lablink/issues)
- Open a [new discussion](https://github.com/talmolab/lablink/discussions)
- Open an [issue](https://github.com/talmolab/lablink/issues/new) if bug/feature

### Communication

- **Be patient**: Maintainers are volunteers
- **Be clear**: Provide context and details
- **Be respectful**: Follow code of conduct
- **Be helpful**: Help others when you can

## Recognition

Contributors are recognized in:
- Git commit history
- GitHub contributors page
- Release notes (for significant contributions)

## License

By contributing, you agree that your contributions will be licensed under the same [BSD-3-Clause License](LICENSE) that covers the project.

## Thank You!

Your contributions make LabLink better for the research community. We appreciate your time and effort! 🎉

---

**Questions about contributing?** Open a [discussion](https://github.com/talmolab/lablink/discussions) or reach out in an [issue](https://github.com/talmolab/lablink/issues).