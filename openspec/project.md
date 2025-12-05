# Project Context

## Purpose
**LabLink** is a dynamic VM allocation and management system for computational research workflows. It automates deployment and management of cloud-based VMs for running research software.

### Key Goals
- Automate allocation of AWS EC2 instances for research workloads
- Provide GPU-enabled VMs for computational research
- Track VM state (available, in-use, failed) via PostgreSQL database
- Enable researchers to request VMs via web interface
- Support containerized research software deployment

## Tech Stack

### Backend
- **Python 3.9+**: Core language for both services
  - Allocator: Python 3.11 (from `uv:python3.11` base image)
  - Client: Python 3.10 (Ubuntu 22.04 default)
- **Flask**: Web framework for allocator service
- **PostgreSQL**: Database for VM state management
- **Hydra/OmegaConf**: Configuration management

### Infrastructure
- **Terraform**: Infrastructure as Code (AWS)
- **Docker**: Containerization for both services
- **AWS EC2**: Virtual machines
- **AWS S3**: Terraform state storage
- **AWS IAM**: Authentication and authorization
- **AWS Route 53**: DNS (optional)

### Development Tools
- **uv**: Python package manager (recommended)
- **pytest**: Testing framework with coverage
- **ruff**: Linting and formatting (PEP 8, max line 88)
- **GitHub Actions**: CI/CD pipelines
- **MkDocs Material**: Documentation

### Package Management
- **Monorepo structure** under `packages/`
  - `packages/allocator/`: Allocator service package
  - `packages/client/`: Client service package
- **PyPI**: Package distribution
- **GHCR**: Docker image registry

## Project Conventions

### Code Style
- **Follow PEP 8** via ruff linting
- **Max line length**: 88 characters (ruff default)
- **Type hints**: Required for public functions
- **Docstrings**: Google style for public functions
- **String formatting**: Use f-strings
- **Import order**: Standard library → Third-party → Local (ruff handles)

### Naming Conventions
- **Files**: `snake_case.py`
- **Functions/Variables**: `snake_case`
- **Classes**: `PascalCase`
- **Constants**: `UPPER_SNAKE_CASE`
- **Private members**: `_leading_underscore`

### Architecture Patterns

#### Monorepo Structure
```
packages/
├── allocator/           # Allocator service package
│   ├── src/lablink_allocator/
│   │   ├── main.py      # Flask application
│   │   ├── database.py  # Database operations
│   │   ├── get_config.py # Config loader
│   │   ├── conf/        # Hydra configuration
│   │   └── terraform/   # Client VM provisioning (part of package)
│   ├── tests/
│   ├── Dockerfile       # Production image (from PyPI)
│   └── Dockerfile.dev   # Development image (local code)
└── client/              # Client service package
    ├── src/lablink_client/
    │   ├── subscribe.py  # Allocator subscription
    │   ├── check_gpu.py  # GPU health checks
    │   └── conf/         # Configuration
    ├── tests/
    ├── Dockerfile        # Production image (from PyPI)
    └── Dockerfile.dev    # Development image (local code)
```

#### Configuration Management
- **Hydra-based** structured configs (`conf/structured_config.py`)
- **Allocator**: Loads from `/config/config.yaml` (Docker mount) or falls back to bundled `conf/config.yaml`
- **Client**: Uses `ALLOCATOR_URL` env var for HTTPS support, falls back to config.yaml
- **Overrides**: Environment variables, command-line args, YAML edits

#### Docker Strategy
- **Two Dockerfiles per package**:
  - `Dockerfile.dev`: Local code with `uv sync`, dev dependencies, for CI/testing
  - `Dockerfile`: PyPI packages with `uv pip install`, production-ready
- **Explicit venv paths**: `/app/.venv` (allocator), `/home/client/.venv` (client)
- **Console scripts**: Entry points defined in `pyproject.toml`

#### Infrastructure Separation
- **Package repo** (this): Python packages, Docker images, client VM Terraform
- **Template repo** (lablink-template): Allocator infrastructure deployment (EC2, DNS, SSL)

### Testing Strategy

#### Unit Tests
- **Framework**: pytest with coverage plugin
- **Minimum coverage**: 90% (enforced in CI)
- **Location**: `tests/` directory per package
- **Mocking**: Mock external dependencies (AWS, database)
- **Terraform tests**: `terraform plan` validation with fixture data

#### Test Execution
```bash
# Run tests
PYTHONPATH=. pytest

# With coverage
PYTHONPATH=. pytest --cov

# Specific test file
PYTHONPATH=. pytest tests/test_api_calls.py
```

#### CI Testing
- **Linting**: `ruff check` on both packages
- **Tests**: pytest with coverage on both packages
- **Docker build**: Verify dev images build and run correctly
- **Terraform**: Validate client VM Terraform plans

### Git Workflow

#### Branching Strategy
- **main**: Production-ready code
- **test**: Staging environment
- **feature branches**: For development work
- **PR required**: All changes via pull requests

#### Commit Conventions
- **Format**: Conventional Commits style
- **Examples**:
  - `feat: Add HTTPS support to client services`
  - `fix: Resolve database connection timeout`
  - `chore: Update dependencies`
  - `docs: Add API endpoint documentation`

#### Release Process
```
1. Development
   └─ PR → CI tests, lint, build dev images

2. Merge to Main
   └─ Auto-build latest Docker images from PyPI

3. Publish to PyPI
   └─ Tag: lablink-{package}_v{version}
      └─ Trigger publish-pip.yml

4. Build Production Images
   └─ Manual trigger with version parameters
```

## Domain Context

### VM State Machine
VMs transition through states:
- **available**: Ready for assignment to users
- **in-use**: Currently assigned and running research workload
- **failed**: Encountered error, needs attention

### Allocator-Client Communication
1. **Subscription**: Client VMs register with allocator on startup
2. **Health checks**: Clients report GPU status periodically
3. **Status updates**: Clients update their in-use status
4. **HTTPS support**: Clients use `ALLOCATOR_URL` env var for secure communication

### VM Lifecycle
1. Admin creates VMs via Terraform (allocator orchestrates)
2. Client VMs boot and run Docker containers
3. Clients subscribe to allocator
4. Users request VMs via web interface
5. Allocator assigns available VMs
6. Clients report health and status
7. Admin can destroy all VMs when needed

### Research Workflow Integration
- Support custom Docker images for research software
- Support custom Git repositories
- GPU health monitoring for ML/DL workloads
- Configurable instance types and AMIs

## Important Constraints

### Security
- **NEVER commit secrets** to version control
- **Change default passwords** immediately in production
- **Rotate SSH keys** every 90 days
- **Use AWS OIDC** for GitHub Actions (no stored credentials)
- **Security groups**: Carefully configure for minimal exposure

### Python Version Compatibility
- **Minimum**: Python 3.9 (both packages)
- **Allocator**: Developed with Python 3.11
- **Client**: Developed with Python 3.10

### AWS Resource Limits
- **EC2 limits**: Check regional instance limits
- **EIP limits**: Limited number of Elastic IPs per region
- **S3**: Single bucket for Terraform state per environment

### Docker Image Size
- **Client images**: ~6GB (includes CUDA, GPU drivers)
- **Build time**: Client builds can be slow due to NVIDIA base image

### Known Issues
- **PostgreSQL restart**: May need manual restart after first deployment
- **Security group persistence**: May need manual deletion when recreating infrastructure
- **SSH key permissions**: Must be `chmod 600`

## External Dependencies

### AWS Services
- **EC2**: Virtual machine instances
- **S3**: Terraform state storage
- **IAM**: Authentication, authorization, OIDC for GitHub Actions
- **Security Groups**: Network security
- **Route 53**: DNS (optional)
- **EIP**: Elastic IP addresses

### Third-Party Services
- **PyPI**: Python package distribution
- **GHCR** (GitHub Container Registry): Docker image storage
- **GitHub Actions**: CI/CD pipelines
- **GitHub Pages**: Documentation hosting

### External Packages
- **Flask**: Web framework
- **psycopg2**: PostgreSQL adapter
- **Hydra/OmegaConf**: Configuration management
- **boto3**: AWS SDK (for future features)
- **pytest**: Testing framework
- **ruff**: Linting and formatting
- **uv**: Python package manager

### Infrastructure Dependencies
- **Terraform**: 1.0+
- **Docker**: 20.10+
- **PostgreSQL**: 13+
- **NVIDIA CUDA**: 12.8.1 (client images)
