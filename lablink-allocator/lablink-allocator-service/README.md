# LabLink Allocator Service

VM allocator service for the LabLink system. This package provides the core Flask-based web application that manages VM allocation, assignment, and lifecycle.

## Features

- 🌐 **Web Interface**: Request and manage VMs via web dashboard
- 🔄 **Dynamic Allocation**: Automatically assign VMs to users based on availability
- 📊 **PostgreSQL Database**: Track VM status, assignments, and health
- 🔐 **Authentication**: Basic HTTP auth for admin endpoints
- ☁️ **AWS Integration**: Deploy and manage EC2 instances via Terraform
- 🐳 **Docker Support**: Run any containerized research software

## Installation

```bash
pip install lablink-allocator-service
```

Or with uv:

```bash
uv pip install lablink-allocator-service
```

## Development

```bash
# Clone the repository
git clone https://github.com/talmolab/lablink.git
cd lablink/lablink-allocator/lablink-allocator-service

# Install with uv
uv sync --extra dev

# Run tests
PYTHONPATH=. pytest

# Run the service
uv run python main.py
```

## Configuration

Configuration is managed via Hydra with `conf/config.yaml`. See the [LabLink documentation](https://talmolab.github.io/lablink/) for detailed configuration options.

## License

BSD-3-Clause License. See [LICENSE](https://github.com/talmolab/lablink/blob/main/LICENSE) for details.

## Links

- **Documentation**: https://talmolab.github.io/lablink/
- **Repository**: https://github.com/talmolab/lablink
- **Issues**: https://github.com/talmolab/lablink/issues
