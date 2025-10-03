# LabLink

**Dynamic VM allocation and management system for computational research workflows.**

[![PyPI - lablink-allocator-service](https://img.shields.io/pypi/v/lablink-allocator-service?label=allocator)](https://pypi.org/project/lablink-allocator-service/)
[![PyPI - lablink-client-service](https://img.shields.io/pypi/v/lablink-client-service?label=client)](https://pypi.org/project/lablink-client-service/)
[![Documentation](https://img.shields.io/badge/docs-latest-blue)](https://talmolab.github.io/lablink/)
[![License](https://img.shields.io/github/license/talmolab/lablink)](LICENSE)

---

## 📦 What's in This Repository

This repository contains the **core LabLink packages, Docker images, and documentation**:

### Python Packages (Published to PyPI)

- **[lablink-allocator-service](lablink-allocator/lablink-allocator-service/)** - VM Allocator Service
  ```bash
  pip install lablink-allocator-service
  ```

- **[lablink-client-service](lablink-client-base/lablink-client-service/)** - Client Service
  ```bash
  pip install lablink-client-service
  ```

### Docker Images (Published to GHCR)

- **lablink-allocator-image** - Allocator service container
- **lablink-client-base-image** - Client service container

### Documentation

- **[LabLink Docs](https://talmolab.github.io/lablink/)** - Comprehensive documentation
  - Getting Started
  - Configuration
  - API Reference
  - Contributing Guide

---

## 🚀 Quick Start

### For Users

**Using the LabLink infrastructure:**

This repository provides the packages and images. For deploying LabLink infrastructure, see the **[LabLink Template Repository](https://github.com/talmolab/lablink-template)** (coming soon).

### For Developers

**Contributing to LabLink packages:**

```bash
# Clone the repository
git clone https://github.com/talmolab/lablink.git
cd lablink

# Install uv (recommended Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Setup allocator service for development
cd lablink-allocator/lablink-allocator-service
uv sync --extra dev

# Setup client service for development
cd ../../lablink-client-base/lablink-client-service
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
├── lablink-allocator/
│   ├── lablink-allocator-service/   # Allocator Python package
│   ├── Dockerfile                   # Production image (from PyPI)
│   └── Dockerfile.dev               # Development image (local code)
├── lablink-client-base/
│   ├── lablink-client-service/      # Client Python package
│   └── lablink-client-base-image/
│       ├── Dockerfile               # Production image (from PyPI)
│       └── Dockerfile.dev           # Development image (local code)
├── docs/                            # MkDocs documentation
├── .github/workflows/               # CI/CD workflows
│   ├── ci.yml                       # Tests, linting, Docker builds
│   ├── publish-packages.yml         # PyPI publishing
│   ├── lablink-images.yml           # Docker image builds & pushes
│   └── docs.yml                     # Documentation deployment
└── terraform/                       # (Infrastructure - being moved to template repo)
```

---

## 📦 Package Versioning

LabLink uses **independent versioning** for its packages:

- **lablink-allocator-service**: [![PyPI](https://img.shields.io/pypi/v/lablink-allocator-service)](https://pypi.org/project/lablink-allocator-service/)
- **lablink-client-service**: [![PyPI](https://img.shields.io/pypi/v/lablink-client-service)](https://pypi.org/project/lablink-client-service/)

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
4. Run tests: `cd lablink-allocator/lablink-allocator-service && uv run pytest`
5. Commit: `git commit -m "feat: add my feature"`
6. Push and open a Pull Request

---

## 🔗 Related Repositories

- **[LabLink Template](https://github.com/talmolab/lablink-template)** _(coming soon)_ - Infrastructure deployment template using LabLink packages

---

## 📝 License

[BSD-3-Clause License](LICENSE)

---

## 🙏 Acknowledgments

LabLink is developed by the [Talmo Lab](https://github.com/talmolab) for the research community.

---

**Questions?** Check the [FAQ](https://talmolab.github.io/lablink/faq/) or open an [issue](https://github.com/talmolab/lablink/issues).
