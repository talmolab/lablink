# lablink-allocator-service

**VM allocator service for the LabLink system.**

[![PyPI version](https://img.shields.io/pypi/v/lablink-allocator-service)](https://pypi.org/project/lablink-allocator-service/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/github/license/talmolab/lablink)](https://github.com/talmolab/lablink/blob/main/LICENSE)

This package provides the core Flask-based web application that manages VM allocation, assignment, and lifecycle for computational research workflows.

---

## Features

- 🌐 **Web Interface**: Request and manage VMs via web dashboard
- 🔄 **Dynamic Allocation**: Automatically assign VMs to users based on availability
- 📊 **PostgreSQL Database**: Track VM status, assignments, and health
- 🔐 **Authentication**: Basic HTTP auth for admin endpoints
- ☁️ **AWS Integration**: Integrates with AWS EC2 via infrastructure templates
- 🐳 **Docker Support**: Run any containerized research software
- 🔍 **Real-time Monitoring**: Track VM health and status
- 🌐 **Optional DNS**: Support for custom domain configuration

---

## Installation

### From PyPI

```bash
pip install lablink-allocator-service
```

### With uv (Recommended)

```bash
uv pip install lablink-allocator-service
```

---

## Quick Start

### Basic Usage

```python
from lablink_allocator_service import main

# Run the Flask application
if __name__ == "__main__":
    main.app.run(host="0.0.0.0", port=5000)
```

### Configuration

Configuration is managed via Hydra with `conf/config.yaml`:

```yaml
db:
  dbname: "lablink"
  user: "lablink"
  password: "your_password"
  host: "localhost"
  port: 5432

app:
  admin_user: "admin"
  admin_password: "secure_password"
  region: "us-west-2"

machine:
  instance_type: "g4dn.xlarge"
  docker_image: "your-registry/your-image:tag"
```

See the [Configuration Guide](https://talmolab.github.io/lablink/configuration/) for detailed options.

---

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/talmolab/lablink.git
cd lablink/lablink-allocator/lablink-allocator-service

# Install with development dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov=src/lablink_allocator_service

# Run linting
uv run ruff check src tests
```

### Project Structure

```
lablink-allocator-service/
├── src/
│   └── lablink_allocator_service/
│       ├── main.py              # Flask application
│       ├── database.py          # Database operations
│       ├── conf/                # Configuration files
│       ├── templates/           # HTML templates
│       └── utils/               # Utility modules
├── tests/                       # Test suite
├── pyproject.toml               # Package configuration
└── README.md                    # This file
```

---

## API Endpoints

### Public Endpoints

- `GET /` - Home page
- `POST /request_vm` - Request VM assignment
- `GET /admin` - Admin dashboard (requires auth)

### Internal Endpoints

- `POST /vm_startup` - Client VM registration
- `POST /vm_update` - Client VM status updates

See the [API Reference](https://talmolab.github.io/lablink/reference/allocator/) for complete documentation.

---

## Deployment

This package is designed to be deployed as part of the LabLink infrastructure. For deployment instructions, see the **[LabLink Template Repository](https://github.com/talmolab/lablink-template)** (coming soon).

### Docker Deployment

The allocator service is containerized and published to GHCR. See [lablink-allocator](../) for the Docker image.

---

## Documentation

- **[Full Documentation](https://talmolab.github.io/lablink/)** - Complete guide
- **[Configuration](https://talmolab.github.io/lablink/configuration/)** - Configuration options
- **[API Reference](https://talmolab.github.io/lablink/reference/allocator/)** - API documentation
- **[Contributing](https://talmolab.github.io/lablink/contributing/)** - Development guide

---

## Contributing

Contributions are welcome! Please see the [Contributing Guide](https://talmolab.github.io/lablink/contributing/) for details.

### Quick Contribution Workflow

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make changes and add tests
4. Run tests: `uv run pytest`
5. Run linting: `uv run ruff check src tests`
6. Commit: `git commit -m "feat(allocator): add my feature"`
7. Push and open a Pull Request

---

## Changelog

See the [Allocator Changelog](https://talmolab.github.io/lablink/changelog-allocator/) for release history.

---

## License

BSD-3-Clause License. See [LICENSE](https://github.com/talmolab/lablink/blob/main/LICENSE) for details.

---

## Links

- **PyPI**: https://pypi.org/project/lablink-allocator-service/
- **Documentation**: https://talmolab.github.io/lablink/
- **Repository**: https://github.com/talmolab/lablink
- **Issues**: https://github.com/talmolab/lablink/issues
- **Discussions**: https://github.com/talmolab/lablink/discussions

---

**Questions?** Check the [FAQ](https://talmolab.github.io/lablink/faq/) or open an [issue](https://github.com/talmolab/lablink/issues).
