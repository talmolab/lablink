# LabLink

**Cloud-based virtual teaching lab accessible through Chrome browser.**

[![PyPI - lablink-allocator-service](https://img.shields.io/pypi/v/lablink-allocator-service?label=allocator)](https://pypi.org/project/lablink-allocator-service/)
[![PyPI - lablink-client-service](https://img.shields.io/pypi/v/lablink-client-service?label=client)](https://pypi.org/project/lablink-client-service/)
[![PyPI - lablink-cli](https://img.shields.io/pypi/v/lablink-cli?label=cli)](https://pypi.org/project/lablink-cli/)
[![Documentation](https://img.shields.io/badge/docs-latest-blue)](https://talmolab.github.io/lablink/)
[![License](https://img.shields.io/github/license/talmolab/lablink)](LICENSE)

---

## 📦 What's in This Repository

This repository contains the **core LabLink packages, Docker images, and documentation**:

### Python Packages (Published to PyPI)

- **[lablink-allocator](packages/allocator/)** - VM Allocator Service
  ```bash
  pip install lablink-allocator
  ```

- **[lablink-client](packages/client/)** - Client Service
  ```bash
  pip install lablink-client
  ```

- **[lablink-cli](packages/cli/)** - Command-line tool to deploy and manage LabLink infrastructure
  ```bash
  uv tool install lablink-cli
  ```

### Docker Images (Published to GHCR)

Production images are built from PyPI packages and tagged with specific versions:

- **lablink-allocator-image** - Allocator service container
  ```bash
  docker pull ghcr.io/talmolab/lablink-allocator-image:0.0.2a0
  docker pull ghcr.io/talmolab/lablink-allocator-image:latest
  ```

- **lablink-client-base-image** - Client service container
  ```bash
  docker pull ghcr.io/talmolab/lablink-client-base-image:0.0.7a0
  docker pull ghcr.io/talmolab/lablink-client-base-image:latest
  ```

**Available Tags:**
- `<version>` (e.g., `0.0.2a0`) - Specific package version (recommended for production)
- `latest` - Latest stable release
- `linux-amd64-latest` - Latest for specific platform
- `<sha>` - Specific git commit
- `linux-amd64-test` - Development/testing builds

See [Docker Image Tags](https://talmolab.github.io/lablink/workflows/#image-tagging-strategy) for complete tagging strategy.

### Documentation

- **[LabLink Docs](https://talmolab.github.io/lablink/)** - Comprehensive documentation
  - Getting Started
  - Configuration
  - API Reference
  - Contributing Guide

---

## 🚀 Quick Start

### For Users

**Using LabLink:**

This repository provides the **Python packages and Docker images**. To deploy LabLink infrastructure (allocator EC2, DNS, etc.), use the **[LabLink Template Repository](https://github.com/talmolab/lablink-template)**.

### For Developers

**Contributing to LabLink packages:**

```bash
# Clone the repository
git clone https://github.com/talmolab/lablink.git
cd lablink

# Install uv (recommended Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Setup allocator service for development
cd packages/allocator
uv sync --extra dev

# Setup client service for development
cd ../client
uv sync --extra dev
```

See the [Contributing Guide](https://talmolab.github.io/lablink/contributing/) for detailed development instructions.

---

## 📚 Documentation

- **[Full Documentation](https://talmolab.github.io/lablink/)** - Complete guide
- **[Architecture](https://talmolab.github.io/lablink/architecture/)** - System design
- **[Configuration](https://talmolab.github.io/lablink/configuration/)** - Configuration options
- **[API Reference](https://talmolab.github.io/lablink/reference/)** - Package APIs
- **[Contributing](https://talmolab.github.io/lablink/contributing/)** - Contribution guide

---

## 🏗️ Repository Structure

```
lablink/
├── packages/
│   ├── allocator/                   # Allocator Python package
│   │   ├── src/lablink_allocator/   # Source code
│   │   │   └── terraform/           # Client VM Terraform (part of package)
│   │   ├── tests/                   # Unit tests including Terraform tests
│   │   ├── Dockerfile               # Production image (from PyPI)
│   │   └── Dockerfile.dev           # Development image (local code)
│   ├── client/                      # Client Python package
│   │   ├── src/lablink_client/      # Source code
│   │   ├── tests/                   # Unit tests
│   │   ├── Dockerfile               # Production image (from PyPI)
│   │   └── Dockerfile.dev           # Development image (local code)
│   └── cli/                         # CLI Python package (Typer + Textual)
│       ├── src/lablink_cli/         # Source code (commands, TUI, config)
│       └── tests/                   # Unit tests
├── docs/                            # MkDocs documentation
└── .github/workflows/               # CI/CD workflows
    ├── ci.yml                       # Tests, linting, Docker builds
    ├── publish-pip.yml              # PyPI publishing
    ├── lablink-images.yml           # Docker image builds & pushes
    └── docs.yml                     # Documentation deployment
```

**Note**: Infrastructure deployment code (allocator EC2, DNS, etc.) has been moved to [lablink-template](https://github.com/talmolab/lablink-template).

---

## 📦 Package Versioning

LabLink uses **independent versioning** for its packages:

- **lablink-allocator-service**: [![PyPI](https://img.shields.io/pypi/v/lablink-allocator-service)](https://pypi.org/project/lablink-allocator-service/)
- **lablink-client-service**: [![PyPI](https://img.shields.io/pypi/v/lablink-client-service)](https://pypi.org/project/lablink-client-service/)
- **lablink-cli**: [![PyPI](https://img.shields.io/pypi/v/lablink-cli)](https://pypi.org/project/lablink-cli/)

See the [Release Process](https://talmolab.github.io/lablink/contributing/#release-process) for how releases are managed.

---

## 🤝 Contributing

We welcome contributions! Please see:

- **[Contributing Guide](https://talmolab.github.io/lablink/contributing/)** - How to contribute
- **[Developer Guide (CLAUDE.md)](CLAUDE.md)** - Developer-focused overview
- **[Code of Conduct](https://talmolab.github.io/lablink/contributing/#code-of-conduct)** - Community guidelines

### Quick Contributing Workflow

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make changes and add tests
4. Run tests: `cd packages/allocator && uv run pytest`
5. Commit: `git commit -m "feat: add my feature"`
6. Push and open a Pull Request

---

## 🔗 Related Repositories

- **[LabLink Template](https://github.com/talmolab/lablink-template)** - Infrastructure deployment template using LabLink packages

---

## 📝 License

[BSD-3-Clause License](LICENSE)

---

## 🙏 Acknowledgments

LabLink is developed by the [Talmo Lab](https://github.com/talmolab) for the research community.

---

**Questions?** Check the [FAQ](https://talmolab.github.io/lablink/faq/) or open an [issue](https://github.com/talmolab/lablink/issues).
