# lablink-client-service

**Client service for LabLink VM instances.**

[![PyPI version](https://img.shields.io/pypi/v/lablink-client-service)](https://pypi.org/project/lablink-client-service/)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/github/license/talmolab/lablink)](https://github.com/talmolab/lablink/blob/main/LICENSE)

This package runs on client VM instances to communicate with the LabLink allocator, report health status, and manage containerized workloads.

---

## Features

- 📡 **Allocator Subscription**: Automatically registers with the allocator service
- 💓 **Health Monitoring**: Reports GPU and system health status
- 🔄 **Status Updates**: Communicates VM availability and usage
- 🐳 **Docker Integration**: Manages containerized research workloads
- ⚡ **GPU Support**: Monitors NVIDIA GPU health and availability
- 🔧 **Configurable**: Flexible configuration via Hydra

---

## Installation

### From PyPI

```bash
pip install lablink-client-service
```

### With uv (Recommended)

```bash
uv pip install lablink-client-service
```

---

## Quick Start

### Running the Service

The client service provides a `subscribe` command that connects to the allocator:

```bash
subscribe allocator.host=your-allocator.com allocator.port=5000
```

Or use the Python module:

```bash
python -m lablink_client_service.subscribe allocator.host=your-allocator.com allocator.port=5000
```

### Configuration

Configuration is managed via Hydra with `conf/config.yaml`:

```yaml
allocator:
  host: "allocator.example.com"
  port: 5000

client:
  software: "your-research-software"
```

You can override configuration at runtime:

```bash
subscribe allocator.host=new-host.com allocator.port=8080 client.software=my-software
```

See the [Configuration Guide](https://talmolab.github.io/lablink/configuration/) for detailed options.

---

## Usage in VM Instances

The client service is designed to run as a startup script in client VMs:

1. **Automatic Registration**: Subscribes to the allocator on VM startup
2. **Health Reporting**: Continuously monitors and reports system health
3. **Status Updates**: Notifies allocator of availability changes
4. **Workload Management**: Manages Docker containers for research tasks

The service runs continuously and handles:
- GPU health checks
- Process monitoring
- Status synchronization with allocator
- Automatic recovery from failures

---

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/talmolab/lablink.git
cd lablink/lablink-client-base/lablink-client-service

# Install with development dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov=src/lablink_client_service

# Run linting
uv run ruff check src tests
```

### Project Structure

```
lablink-client-service/
├── src/
│   └── lablink_client_service/
│       ├── subscribe.py              # Main subscription service
│       ├── check_gpu.py              # GPU health monitoring
│       ├── update_inuse_status.py    # Status update service
│       ├── conf/                     # Configuration files
│       └── utils/                    # Utility modules
├── tests/                            # Test suite
├── pyproject.toml                    # Package configuration
└── README.md                         # This file
```

### Entry Points

The package provides the following entry points:

- `subscribe` - Main service for connecting to allocator
- `check_gpu` - GPU health check utility
- `update_inuse_status` - Status update utility

---

## Components

### Subscription Service (`subscribe.py`)

Connects to the allocator and maintains communication:

```python
from lablink_client_service import subscribe

# Run subscription service
subscribe.main()
```

### GPU Health Check (`check_gpu.py`)

Monitors NVIDIA GPU health and availability:

```python
from lablink_client_service import check_gpu

# Check GPU status
status = check_gpu.check_gpu_health()
```

### Status Updates (`update_inuse_status.py`)

Reports VM usage status to allocator:

```python
from lablink_client_service import update_inuse_status

# Update VM status
update_inuse_status.update_status(in_use=True)
```

---

## Deployment

This package is designed to be deployed in client VMs as part of the LabLink infrastructure. For deployment instructions, see the **[LabLink Template Repository](https://github.com/talmolab/lablink-template)** (coming soon).

### Docker Deployment

The client service is containerized and published to GHCR. See [lablink-client-base-image](../lablink-client-base-image/) for the Docker image.

---

## Documentation

- **[Full Documentation](https://talmolab.github.io/lablink/)** - Complete guide
- **[Configuration](https://talmolab.github.io/lablink/configuration/)** - Configuration options
- **[API Reference](https://talmolab.github.io/lablink/reference/client/)** - API documentation
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
6. Commit: `git commit -m "feat(client): add my feature"`
7. Push and open a Pull Request

---

## Changelog

See the [Client Changelog](https://talmolab.github.io/lablink/changelog-client/) for release history.

---

## License

BSD-3-Clause License. See [LICENSE](https://github.com/talmolab/lablink/blob/main/LICENSE) for details.

---

## Links

- **PyPI**: https://pypi.org/project/lablink-client-service/
- **Documentation**: https://talmolab.github.io/lablink/
- **Repository**: https://github.com/talmolab/lablink
- **Issues**: https://github.com/talmolab/lablink/issues
- **Discussions**: https://github.com/talmolab/lablink/discussions

---

**Questions?** Check the [FAQ](https://talmolab.github.io/lablink/faq/) or open an [issue](https://github.com/talmolab/lablink/issues).
