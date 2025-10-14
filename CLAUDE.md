# Claude Developer Guide

This file provides context and guidance for Claude (or other AI assistants) working on the LabLink codebase.

## Project Overview

**LabLink** is a dynamic VM allocation and management system for computational research workflows. It automates deployment and management of cloud-based VMs for running research software.

## Repository Structure

```
lablink/
├── .github/
│   └── workflows/              # GitHub Actions CI/CD
│       ├── ci.yml              # Unit tests, linting, Terraform tests
│       ├── docs.yml            # Documentation deployment
│       ├── lablink-images.yml  # Docker image building
│       └── publish-pip.yml     # PyPI package publishing
├── docs/                       # MkDocs documentation
│   ├── *.md                    # Documentation pages
│   ├── scripts/                # Doc generation scripts
│   └── assets/                 # Images, diagrams
├── packages/                   # Python packages (monorepo)
│   ├── allocator/              # Allocator service package
│   │   ├── src/lablink_allocator/
│   │   │   ├── main.py         # Flask application
│   │   │   ├── database.py     # Database operations
│   │   │   ├── get_config.py   # Config loader (reads /config or local)
│   │   │   ├── conf/
│   │   │   │   ├── structured_config.py  # Hydra config schema
│   │   │   │   └── config.yaml # Local dev fallback config
│   │   │   ├── terraform/      # Terraform for client VMs (part of package)
│   │   │   │   ├── main.tf     # Client VM provisioning
│   │   │   │   ├── variables.tf
│   │   │   │   └── outputs.tf
│   │   │   └── utils/          # Utility modules
│   │   ├── tests/              # Unit tests
│   │   │   ├── terraform/      # Client VM Terraform tests
│   │   │   └── *.py            # Other unit tests
│   │   ├── Dockerfile          # Allocator Docker image (production)
│   │   ├── Dockerfile.dev      # Allocator Docker image (development)
│   │   └── pyproject.toml      # Package metadata
│   └── client/                 # Client service package
│       ├── src/lablink_client/
│       │   ├── subscribe.py    # Allocator subscription (HTTPS support)
│       │   ├── check_gpu.py    # GPU health checks (HTTPS support)
│       │   ├── update_inuse_status.py  # Status updates (HTTPS support)
│       │   └── conf/           # Configuration
│       ├── tests/              # Unit tests
│       ├── Dockerfile          # Client Docker image (production)
│       ├── Dockerfile.dev      # Client Docker image (development)
│       ├── start.sh            # Container entry point
│       └── pyproject.toml      # Package metadata
├── mkdocs.yml                  # Documentation configuration
├── pyproject.toml              # Workspace dependencies (docs, dev tools)
├── README.md                   # Repository README
├── CLAUDE.md                   # This file
└── MIGRATION_PLAN.md           # Migration status and history
```

**Note**: Allocator infrastructure deployment (EC2, DNS, EIP, Lambda, etc.) has been moved to the [lablink-template](https://github.com/talmolab/lablink-template) repository. This repository contains only the Python packages and Docker images. The allocator package includes client VM Terraform as part of its core functionality.

## Technology Stack

### Core Technologies
- **Python 3.9+**: Backend services
  - Allocator: Python 3.11 (from `uv:python3.11` base image)
  - Client: Python 3.10 (Ubuntu 22.04 default)
  - Both meet `pyproject.toml` requirement: `>=3.9`
- **Flask**: Web framework for allocator
- **PostgreSQL**: Database for VM state
- **Docker**: Containerization
- **Terraform**: Infrastructure as Code (AWS)
- **Hydra/OmegaConf**: Configuration management

### CI/CD & Tooling
- **GitHub Actions**: CI/CD pipelines
- **pytest**: Testing framework
- **ruff**: Linting and formatting
- **uv**: Python package manager (recommended)
- **MkDocs Material**: Documentation

### AWS Services
- **EC2**: Virtual machines
- **S3**: Terraform state storage
- **IAM**: Authentication and authorization
- **Security Groups**: Network security
- **Route 53**: DNS (optional)

## Key Concepts

### Allocator
- Flask web application running on EC2
- Manages VM allocation requests
- Maintains PostgreSQL database of VM states
- Provides web UI and API endpoints
- Orchestrates client VM creation via Terraform

### Client VMs
- Dynamically spawned EC2 instances
- Run containerized research software
- Report health status to allocator
- Support custom Docker images and repositories

### VM States
- **available**: Ready for assignment
- **in-use**: Currently assigned to user
- **failed**: Encountered error

### Environments
- **dev**: Local development, local Terraform state
- **test**: Staging environment, S3 backend
- **prod**: Production, S3 backend, pinned image versions

## Configuration System

Configuration uses **Hydra** with structured configs.

### Infrastructure Deployment Configuration
**Location**: [lablink-template](https://github.com/talmolab/lablink-template) repository

The template repository contains production configuration for deploying the allocator infrastructure (EC2, DNS, SSL, etc.).

### Package Development Configuration
**Location**: `packages/allocator/src/lablink_allocator/conf/config.yaml`

This is the local development configuration used when developing the allocator package.

**Key sections**:
- `db`: PostgreSQL connection settings
- `machine`: Client VM specifications (instance type, AMI ID, Docker image, repository)
- `app`: Admin credentials, AWS region
- `dns`: DNS configuration
- `ssl`: SSL provider configuration
- `bucket_name`: S3 bucket for Terraform state

The allocator uses `get_config()` which:
1. First tries to load `/config/config.yaml` (mounted in Docker from infrastructure deployment via template)
2. Falls back to the bundled `conf/config.yaml` for local package development and testing

**Note**: The bundled config is used when developing the allocator package itself, not for infrastructure deployment. For infrastructure deployment, configuration comes from the template repository.

### Client Configuration
**Location**: `packages/client/src/lablink_client/conf/config.yaml`

**Key sections**:
- `allocator`: Allocator host and port (overridden by `ALLOCATOR_URL` env var for HTTPS)
- `client`: Software identifier

**HTTPS Support**: Client services (subscribe.py, check_gpu.py, update_inuse_status.py) use `ALLOCATOR_URL` environment variable to support HTTPS allocators, falling back to `http://host:port` if not set.

### Overriding Configuration
- Edit YAML files directly (infrastructure config for production)
- Environment variables (`ALLOCATOR_URL`, `CONFIG_DIR`, `CONFIG_NAME`)
- Hydra command-line overrides: `python main.py db.password=newpass`
- Docker environment variables (passed via user_data.sh)

## Development Workflow

### Local Development

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Allocator
cd packages/allocator
uv sync --extra dev
uv run lablink-allocator

# Client
cd packages/client
uv sync --extra dev
uv run subscribe
```

### Running Tests

```bash
# Allocator tests
cd packages/allocator
PYTHONPATH=. pytest

# Client tests
cd packages/client
PYTHONPATH=. pytest

# With coverage
PYTHONPATH=. pytest --cov
```

### Linting

```bash
# Check code
ruff check .

# Auto-fix
ruff check --fix .

# Format
ruff format .
```

### Building Docker Images

#### Via GitHub Actions (Recommended)

**Production builds with version tags** (after publishing to PyPI):
```bash
# Trigger production builds for both images with their versions
gh workflow run lablink-images.yml \
  -f environment=prod \
  -f allocator_version=0.0.2a0 \
  -f client_version=0.0.7a0
```

This creates Docker images tagged with:
- `ghcr.io/talmolab/lablink-allocator-image:0.0.2a0` (version tag)
- `ghcr.io/talmolab/lablink-client-base-image:0.0.7a0` (version tag)
- `latest` tags for both images
- Plus platform and metadata tags

See [Image Tagging Strategy](https://talmolab.github.io/lablink/workflows/#image-tagging-strategy) for complete tag list.

**Development builds** (automatic on PR/push to test):
- Automatically triggered by PRs or pushes to `test` branch
- Uses `Dockerfile.dev` with local code
- Tagged with `-test` suffix (e.g., `linux-amd64-test`)

#### Local Development Builds

**Development Builds (Local Code)**:
```bash
# Allocator (dev) - uses local code
docker build -t lablink-allocator:dev -f packages/allocator/Dockerfile.dev .

# Client (dev) - uses local code
docker build -t lablink-client:dev -f packages/client/Dockerfile.dev .
```

**Production Builds (From PyPI)**:
```bash
# Allocator (prod) - installs from PyPI
docker build -t lablink-allocator:0.0.2a0 \
  --build-arg PACKAGE_VERSION=0.0.2a0 \
  -f packages/allocator/Dockerfile .

# Client (prod) - installs from PyPI
docker build -t lablink-client:0.0.7a0 \
  --build-arg PACKAGE_VERSION=0.0.7a0 \
  -f packages/client/Dockerfile .
```

## Docker Strategy

### Dockerfile Types

**`Dockerfile.dev`** (Development/CI):
- Copies local source code directly into the image
- Uses `uv sync --extra dev` with lockfile (`uv.lock`) for reproducible builds
- Installs dev dependencies (pytest, ruff, coverage)
- Creates virtual environment with explicit path via `UV_PROJECT_ENVIRONMENT`
- Fast iteration (lockfile prevents dependency resolution on each build)
- Used by CI workflows on PRs and test branches
- No PyPI dependency required

**Dockerfile** (Production):
- Installs Python packages from PyPI using `uv pip install`
- Accepts `PACKAGE_VERSION` build argument
- Uses specific pinned versions from PyPI
- No source code included (smaller image)
- No dev dependencies (even smaller image)
- Explicit venv paths with `--python=/path/to/venv/bin/python` flag
- Used for main/prod deployments

### Virtual Environment Setup

Both services use **explicit venv paths** to avoid path resolution issues.

**Allocator:**
- **Location**: `/app/.venv` (both dev and production)
- **Python**: 3.11 (from `ghcr.io/astral-sh/uv:python3.11` base image)
- **Dockerfile.dev**: `uv sync --extra dev` in `/app/lablink-allocator`, symlink to `/app/.venv`
- **Dockerfile**: `uv venv /app/.venv && uv pip install --python=/app/.venv/bin/python lablink-allocator==${VERSION}`
- **start.sh** activates: `source /app/.venv/bin/activate`

**Client:**
- **Location**: `/home/client/.venv` (both dev and production)
- **Python**: 3.10 (Ubuntu 22.04 default from `nvidia/cuda:12.8.1` base image)
- **Dockerfile.dev**: `uv pip install -e ".[dev]"` with explicit venv creation
- **Dockerfile**: `uv venv /home/client/.venv && uv pip install --python=/home/client/.venv/bin/python lablink-client==${VERSION}`
- **start.sh** activates: `source /home/client/.venv/bin/activate`

**Important**: Both use `--python=/path/to/venv/bin/python` flag to explicitly specify which Python interpreter to use, ensuring consistency regardless of system PATH.

### Console Scripts

Both services provide console script entry points defined in `pyproject.toml`:

**Allocator:**
- `lablink-allocator` - Runs the Flask application
- `generate-init-sql` - Generates PostgreSQL init script

**Client:**
- `check_gpu` - GPU health check
- `subscribe` - Allocator subscription service
- `update_inuse_status` - Status update service

These are automatically installed when the package is installed and available in the venv or system PATH.

## CI/CD Workflows

### Workflow Overview

**`ci.yml`** - Continuous Integration
- **Triggers**: PRs affecting service code or workflows
- **Jobs**:
  - **Lint**: Run `ruff check` on both packages
  - **Test**: Run `pytest` with coverage on both packages
    - Includes Terraform plan tests for client VM creation
    - Terraform installed automatically for allocator tests
    - Backend config removed for testing (no S3 required)
  - **Docker Build Test** (allocator only):
    - Build `Dockerfile.dev` image
    - Verify venv activation and paths
    - Verify entry points are importable and callable (catches indentation bugs)
    - Verify console scripts exist (`lablink-allocator`, `generate-init-sql`)
    - Verify dev dependencies installed (pytest, ruff, coverage with versions)
    - Verify package imports work (main, database, get_config)
    - Verify `uv sync` installation
- **Note**: Client Docker build test skipped due to large image size (~6GB with CUDA)

**`lablink-images.yml`** - Docker Image Building
- **Triggers**: PRs, pushes to main/test, manual dispatch
- **Smart Dockerfile Selection**:
  - PR/test branch → `Dockerfile.dev` (local code with `uv sync`)
  - Main branch → `Dockerfile` (from PyPI with default version)
  - Manual dispatch with version parameters → `Dockerfile` (from PyPI with specific versions)
- **Image Tags** (vary by trigger):
  - **Production with version** (manual trigger): `0.0.2a0`, `linux-amd64-0.0.2a0`, `latest`, `linux-amd64-latest`, `<sha>`, plus metadata tags
  - **Main branch** (auto): `latest`, `linux-amd64-latest`, `<sha>`, metadata tags (no version tags)
  - **Test/PR** (auto): All tags with `-test` suffix
- **Post-Build Verification**:
  - `verify-allocator`: Tests entry point callability, console scripts, imports, dev deps
  - `verify-client`: Tests entry point callability, console scripts, imports, uv availability, dev deps
  - Verifies entry points are importable and callable (prevents runtime failures)
  - Pulls pushed images and runs validation tests
- **Deployment**: Pushes to `ghcr.io/talmolab/`
- **Manual Production Build**:
  ```bash
  gh workflow run lablink-images.yml \
    -f environment=prod \
    -f allocator_version=0.0.2a0 \
    -f client_version=0.0.7a0
  ```

**`publish-pip.yml`** - PyPI Publishing
- **Triggers**: Git tags (e.g., `lablink-allocator-service_v0.0.2a0`), manual dispatch
- **Features**:
  - Branch verification (must be from main)
  - Version verification (tag must match pyproject.toml)
  - Package metadata validation
  - Linting and tests before publish
  - Dry-run mode available
  - Per-package control (allocator/client)
- **Post-Publish**: Displays manual Docker build command for creating production images
- **Note**: Docker image builds must be triggered manually after publishing

**`docs.yml`** - Documentation Deployment
- **Triggers**: Pushes to main, PRs for docs changes
- **Deployment**: Builds and deploys MkDocs to GitHub Pages

### Release Workflow

```
1. Development
   └─ PR → ci.yml (test, lint, build Dockerfile.dev)
           lablink-images.yml (build dev image with -test tag)

2. Merge to Main
   └─ lablink-images.yml (build prod image from latest PyPI package, no version tag)

3. Publish to PyPI
   └─ Create tag (e.g., lablink-allocator-service_v0.0.2a0)
      └─ publish-pip.yml (publish to PyPI)
         └─ Displays manual Docker build command

4. Build Production Docker Images
   └─ Manually trigger:
      gh workflow run lablink-images.yml -f environment=prod \
        -f allocator_version=0.0.2a0 -f client_version=0.0.7a0
      └─ lablink-images.yml (build prod images with version tags from PyPI)
```

### Package Versioning

- **Format**: Semantic versioning (e.g., `0.0.2a0` for alpha, `0.1.0` for stable)
- **Tag Convention**: `{package-name}_v{version}` (e.g., `lablink-allocator-service_v0.0.2a0`)
- **Docker Tags**: Include package version when built from published packages
- **Current Versions**:
  - Allocator: `0.0.2a0`
  - Client: `0.0.7a0`

## Common Tasks

### Add New API Endpoint

1. Edit `packages/allocator/src/lablink_allocator_service/main.py`
2. Add Flask route:
   ```python
   @app.route('/my-endpoint', methods=['POST'])
   def my_endpoint():
       # Implementation
       return jsonify({'status': 'success'})
   ```
3. Add tests in `tests/test_api_calls.py`
4. Update documentation in `docs/`

### Add New Configuration Option

1. Edit `conf/structured_config.py`:
   ```python
   @dataclass
   class MyNewConfig:
       option: str = field(default="value")
   ```
2. Add to main `Config` dataclass
3. Use in code: `cfg.my_new.option`
4. Document in `docs/configuration.md`

### Modify VM Creation

1. Edit `packages/allocator/src/lablink_allocator_service/terraform/main.tf`
2. Update Terraform resource definitions
3. Test with `terraform plan`
4. Update documentation

### Add New Client Feature

1. Create module in `lablink_client_service/`
2. Add entry point in `__main__.py` or startup script
3. Update Dockerfile if needed
4. Add tests
5. Document in `docs/`

## Code Style Guidelines

### Python
- Follow PEP 8
- Use type hints
- Docstrings for public functions (Google style)
- Max line length: 88 (ruff default)
- Use f-strings for formatting

### Terraform
- Use descriptive resource names
- Tag all resources with `Name`, `Project`, `Environment`
- Use variables for configurable values
- Include `outputs.tf` for important values

### Documentation
- Clear, concise language
- Include examples
- Test all commands before documenting
- Cross-reference related pages

## Database Schema

### `vms` Table

```sql
CREATE TABLE vms (
    id SERIAL PRIMARY KEY,
    hostname VARCHAR(255) NOT NULL UNIQUE,
    email VARCHAR(255),
    status VARCHAR(50) NOT NULL,
    crd_command TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

### Trigger: `notify_vm_update`
Sends PostgreSQL NOTIFY on table changes for real-time updates.

## API Endpoints

### Allocator API

- `GET /`: Home page
- `POST /request_vm`: Request VM assignment
  - Form data: `email`, `crd_command`
  - Returns: VM hostname and status
- `GET /admin`: Admin dashboard (requires auth)
- `POST /admin/create`: Create client VMs
  - Form data: `instance_count`
- `GET /admin/instances`: View VM list
- `POST /admin/destroy`: Destroy all client VMs
- `POST /vm_startup`: Client VM registration
  - Form data: `hostname`

## Security Considerations

### Secrets
- **NEVER** commit secrets to version control
- Use environment variables or AWS Secrets Manager
- Change default passwords immediately
- Rotate SSH keys regularly (every 90 days)

### AWS Authentication
- **GitHub Actions**: Use OIDC (no stored credentials)
- **Local**: Use AWS CLI profiles or environment variables

### Default Passwords (MUST CHANGE)
- Admin password: `IwanttoSLEAP`
- Database password: `lablink`

## Known Issues

### PostgreSQL Restart Required
After first deployment, PostgreSQL may need manual restart:
```bash
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>
sudo docker exec -it <container-id> /etc/init.d/postgresql restart
```

### Security Group Persistence
When destroying and recreating, security groups may need manual deletion if Terraform fails.

### SSH Key Permissions
Always set: `chmod 600 ~/lablink-key.pem`

## Testing Strategy

### Unit Tests
- Mock external dependencies (AWS, database)
- Test individual functions in isolation
- Run in CI on every PR
- Includes Terraform plan tests for client VM creation

### Integration Tests
- Test component interactions
- Require actual database (Docker)
- Run manually or in dedicated CI job

### Terraform Tests
- Validate client VM Terraform configurations
- Run `terraform plan` with fixture data
- Test resource creation, variables, and outputs
- Uses AWS OIDC credentials for provider validation
- Plan-only operation (no resources created)
- Run in CI as part of unit tests

## Package Release Process

### Image Building
1. Push to branch → GitHub Actions builds images
2. Tags: `linux-amd64-latest` (main), `linux-amd64-<branch>-test` (others)
3. Push to ghcr.io

### Infrastructure Deployment
See the [lablink-template](https://github.com/talmolab/lablink-template) repository for infrastructure deployment documentation.

### Package Versioning
- Use semantic versioning: `v1.0.0`, `v1.1.0`
- Tag releases in GitHub
- Pin production deployments to specific tags

## Troubleshooting for Developers

### Import Errors
```bash
export PYTHONPATH=.
pytest
```

### Docker Permission Errors
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### Terraform State Lock
```bash
terraform force-unlock <lock-id>
```

### Can't Access Database
Check PostgreSQL is running:
```bash
sudo docker exec <container-id> pg_isready -U lablink
```

## Documentation System

### Building Docs Locally

**Using uv (Recommended):**
```bash
# Quick test (temporary environment)
uv run --extra docs mkdocs serve
# Open http://localhost:8000

# Or persistent environment
uv venv .venv-docs
source .venv-docs/bin/activate  # macOS/Linux
# .venv-docs\Scripts\activate  # Windows
uv sync --extra docs
mkdocs serve
```

**Using pip:**
```bash
pip install -e ".[docs]"
mkdocs serve
# Open http://localhost:8000
```

### Adding New Page
1. Create `docs/new-page.md`
2. Add to `nav` in `mkdocs.yml`
3. Test with `mkdocs serve`
4. Push to trigger auto-deployment

### Auto-Generated Content
- **API Reference**: From Python docstrings (mkdocstrings)
- **Changelog**: From git tags/commits (`docs/scripts/gen_changelog.py`)

## Important Files

### Configuration
- `packages/allocator/src/lablink_allocator_service/conf/config.yaml`: Allocator package config (local dev)
- `packages/client/src/lablink_client_service/conf/config.yaml`: Client package config

### Entry Points
- `packages/allocator/src/lablink_allocator_service/main.py`: Allocator Flask app
- `packages/client/src/lablink_client_service/subscribe.py`: Client subscription service

### Infrastructure
- `packages/allocator/src/lablink_allocator_service/terraform/main.tf`: Client VM Terraform (part of allocator package)
- For allocator infrastructure deployment, see [lablink-template](https://github.com/talmolab/lablink-template)

### CI/CD
- `.github/workflows/ci.yml`: Tests, linting, Docker builds
- `.github/workflows/lablink-images.yml`: Docker image publishing
- `.github/workflows/publish-pip.yml`: PyPI package publishing
- `.github/workflows/docs.yml`: Documentation deployment

## Resources

- **Documentation**: https://talmolab.github.io/lablink/
- **Repository**: https://github.com/talmolab/lablink
- **Issues**: https://github.com/talmolab/lablink/issues

## Notes for Claude

### When Making Changes
1. **Read before editing**: Always read existing code/docs first
2. **Follow patterns**: Match existing code style and structure
3. **Test changes**: Provide commands to test changes
4. **Update docs**: Update relevant documentation pages
5. **Consider security**: Never introduce vulnerabilities

### When Adding Features
1. **Configuration**: Add to structured config if user-facing
2. **Tests**: Add unit tests for new functionality
3. **Documentation**: Document in appropriate docs page
4. **Examples**: Provide usage examples

### When Fixing Bugs
1. **Understand root cause**: Don't just patch symptoms
2. **Add regression test**: Prevent future occurrences
3. **Update troubleshooting**: Add to `docs/troubleshooting.md` if user-facing

### Code Review Checklist
- [ ] Code follows existing patterns
- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] No secrets committed
- [ ] Backwards compatible (or documented breaking change)
- [ ] Error handling included
- [ ] Logging added for debugging

## Getting Help

For questions about this project, consult:
1. Documentation in `docs/`
2. Existing code and tests
3. GitHub issues for similar problems
4. README files in subdirectories