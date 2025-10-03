# Claude Developer Guide

This file provides context and guidance for Claude (or other AI assistants) working on the LabLink codebase.

## Project Overview

**LabLink** is a dynamic VM allocation and management system for computational research workflows. It automates deployment and management of cloud-based VMs for running research software.

## Repository Structure

```
lablink/
├── .github/
│   └── workflows/              # GitHub Actions CI/CD
│       ├── ci.yml              # Unit tests and linting
│       ├── docs.yml            # Documentation deployment
│       ├── lablink-images.yml  # Docker image building
│       ├── lablink-allocator-terraform.yml  # Infrastructure deployment
│       ├── lablink-allocator-destroy.yml    # Destroy workflow
│       └── client-vm-infrastructure-test.yml  # E2E testing
├── docs/                       # MkDocs documentation
│   ├── *.md                    # Documentation pages
│   ├── scripts/                # Doc generation scripts
│   └── assets/                 # Images, diagrams
├── lablink-allocator/          # Allocator service
│   ├── Dockerfile              # Allocator Docker image (production)
│   ├── Dockerfile.dev          # Allocator Docker image (development)
│   ├── main.tf                 # Terraform for allocator EC2
│   ├── backend-*.hcl           # Terraform backends (dev/test/prod)
│   └── lablink-allocator-service/
│       ├── main.py             # Flask application
│       ├── database.py         # Database operations
│       ├── conf/
│       │   ├── config.yaml     # Configuration
│       │   └── structured_config.py  # Hydra config
│       ├── terraform/          # Terraform for client VMs
│       │   └── main.tf         # Client VM provisioning
│       ├── tests/              # Unit tests
│       └── utils/              # Utility modules
├── lablink-client-base/        # Client service
│   ├── lablink-client-base-image/
│   │   ├── Dockerfile          # Client Docker image (production)
│   │   └── Dockerfile.dev      # Client Docker image (development)
│   └── lablink-client-service/
│       ├── lablink_client_service/
│       │   ├── subscribe.py    # Allocator subscription
│       │   ├── check_gpu.py    # GPU health checks
│       │   ├── update_inuse_status.py  # Status updates
│       │   └── conf/           # Configuration
│       └── tests/              # Unit tests
├── terraform/                  # Shared Terraform modules
├── mkdocs.yml                  # Documentation configuration
├── pyproject.toml              # Python dependencies (docs extra)
├── README.md                   # Repository README
└── CLAUDE.md                   # This file
```

## Technology Stack

### Core Technologies
- **Python 3.9+**: Backend services
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

### Allocator Configuration
**Location**: `lablink-allocator/lablink-allocator-service/conf/config.yaml`

**Key sections**:
- `db`: PostgreSQL connection settings
- `machine`: Client VM specifications (instance type, AMI, Docker image, repository)
- `app`: Admin credentials, AWS region
- `bucket_name`: S3 bucket for Terraform state

### Client Configuration
**Location**: `lablink-client-base/lablink-client-service/lablink_client_service/conf/config.yaml`

**Key sections**:
- `allocator`: Allocator host and port
- `client`: Software identifier

### Overriding Configuration
- Edit YAML files directly
- Environment variables
- Hydra command-line overrides: `python main.py db.password=newpass`
- Docker environment variables

## Development Workflow

### Local Development

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Allocator
cd lablink-allocator/lablink-allocator-service
uv sync --extra dev
uv run python main.py

# Client
cd lablink-client-base/lablink-client-service
uv sync --extra dev
uv run python lablink_client_service/subscribe.py
```

### Running Tests

```bash
# Allocator tests
cd lablink-allocator/lablink-allocator-service
PYTHONPATH=. pytest

# Client tests
cd lablink-client-base/lablink-client-service
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

#### Development Builds (Local Code)
```bash
# Allocator (dev) - uses local code
docker build -t lablink-allocator:dev -f lablink-allocator/Dockerfile.dev .

# Client (dev) - uses local code
docker build -t lablink-client:dev \
  -f lablink-client-base/lablink-client-base-image/Dockerfile.dev \
  lablink-client-base
```

#### Production Builds (From PyPI)
```bash
# Allocator (prod) - installs from PyPI
docker build -t lablink-allocator:0.0.2a0 \
  --build-arg PACKAGE_VERSION=0.0.2a0 \
  -f lablink-allocator/Dockerfile .

# Client (prod) - installs from PyPI
docker build -t lablink-client:0.0.7a0 \
  --build-arg PACKAGE_VERSION=0.0.7a0 \
  -f lablink-client-base/lablink-client-base-image/Dockerfile \
  lablink-client-base
```

## Docker Strategy

### Dockerfile Types

**`Dockerfile.dev`** (Development/CI):
- Copies local source code directly into the image
- Uses `uv sync --extra dev` for installation
- Installs dev dependencies (pytest, ruff, coverage)
- Creates virtual environment at project location
- Fast iteration during development
- Used by CI workflows on PRs and test branches
- No PyPI dependency required

**Dockerfile**  (Production):
- Installs Python packages from PyPI using `uv pip install`
- Accepts `PACKAGE_VERSION` build argument
- Uses specific pinned versions
- No dev dependencies (smaller image)
- Reproducible builds
- Used for main/prod deployments

### Virtual Environment Setup

**Allocator:**
- `Dockerfile.dev`: Creates venv at `/app/lablink-allocator-service/.venv` with symlink at `/app/.venv`
- `Dockerfile`: Creates venv at `/app/.venv` from PyPI package
- `start.sh` activates venv with `source /app/.venv/bin/activate`

**Client:**
- `Dockerfile.dev`: Creates venv at `/home/client/.venv` with editable install
- `Dockerfile`: Creates venv at `/home/client/.venv` from PyPI package
- `start.sh` activates venv with `source /home/client/.venv/bin/activate`

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
- **Triggers**: PRs, pushes to main/test, manual dispatch, `repository_dispatch`
- **Smart Dockerfile Selection**:
  - PR/test branch → `Dockerfile.dev` (local code with `uv sync`)
  - Main branch → `Dockerfile` (from PyPI with default version)
  - After package publish → `Dockerfile` (from PyPI with specific version)
- **Image Tags**:
  - Git SHA (e.g., `abc123-test`)
  - Platform (e.g., `linux-amd64-latest-test`)
  - Package version (e.g., `0.0.2a0`, `linux-amd64-0.0.2a0`) when available
  - Environment suffix (`-test` for non-prod)
- **Post-Build Verification** (new jobs):
  - `verify-allocator`: Tests entry point callability, console scripts, imports, dev deps
  - `verify-client`: Tests entry point callability, console scripts, imports, uv availability, dev deps
  - Verifies entry points are importable and callable (prevents runtime failures)
  - Pulls pushed images and runs validation tests
- **Deployment**: Pushes to `ghcr.io`

**`publish-packages.yml`** - PyPI Publishing
- **Triggers**: Git tags, manual dispatch
- **Features**:
  - Version verification and guardrails
  - Linting and tests before publish
  - Dry-run mode available
  - Per-package control (allocator/client)
- **Integration**: Triggers Docker image rebuild via `repository_dispatch` after successful publish

**`docs.yml`** - Documentation Deployment
- **Triggers**: Pushes to main, PRs for docs changes
- **Deployment**: Builds and deploys MkDocs to GitHub Pages

### Release Workflow

```
1. Development
   └─ PR → ci.yml (test, lint, build Dockerfile.dev)
           lablink-images.yml (build dev image with -test tag)

2. Merge to Main
   └─ lablink-images.yml (build prod image from latest PyPI package)

3. Release
   └─ Create tag (e.g., lablink-allocator-service_v0.0.2a0)
      └─ publish-packages.yml (publish to PyPI)
         └─ repository_dispatch
            └─ lablink-images.yml (build prod image with version tag)
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

1. Edit `lablink-allocator/lablink-allocator-service/main.py`
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

1. Edit `lablink-allocator/lablink-allocator-service/terraform/main.tf`
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

### Integration Tests
- Test component interactions
- Require actual database (Docker)
- Run manually or in dedicated CI job

### E2E Tests
- Test full workflow (allocator → client VM creation)
- Run in `client-vm-infrastructure-test.yml`
- Manual trigger or scheduled

## Deployment Process

### Image Building
1. Push to branch → GitHub Actions builds images
2. Tags: `linux-amd64-latest` (main), `linux-amd64-<branch>-test` (others)
3. Push to ghcr.io

### Infrastructure Deployment
1. Manual: `terraform apply` in `lablink-allocator/`
2. GitHub Actions: Workflow dispatch or push to `test` branch
3. Environments determined by branch or manual selection

### Versioning
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
- `lablink-allocator/lablink-allocator-service/conf/config.yaml`: Main allocator config
- `lablink-client-base/lablink-client-service/lablink_client_service/conf/config.yaml`: Client config

### Entry Points
- `lablink-allocator/lablink-allocator-service/main.py`: Allocator Flask app
- `lablink-client-base/lablink-client-service/lablink_client_service/subscribe.py`: Client subscription service

### Infrastructure
- `lablink-allocator/main.tf`: Allocator EC2 provisioning
- `lablink-allocator/lablink-allocator-service/terraform/main.tf`: Client VM provisioning

### CI/CD
- `.github/workflows/`: All GitHub Actions workflows

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