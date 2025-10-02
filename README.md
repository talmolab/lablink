# LabLink

Dynamic VM allocation and management system for computational research workflows.

## Overview

LabLink automates deployment and management of cloud-based VMs for running research software. It provides a web interface for requesting VMs, tracking their status, and managing computational workloads.

## Quick Start

### Prerequisites

- AWS account with appropriate permissions
- Docker installed locally (for testing)
- Python 3.9+ with `uv` package manager

### Installation

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone https://github.com/talmolab/lablink.git
cd lablink

# Install dependencies
cd lablink-allocator/lablink-allocator-service
uv sync --extra dev
```

### Configuration

Copy the example configuration file and customize it:

```bash
cd lablink-allocator/lablink-allocator-service/conf
cp config.yaml.example config.yaml
# Edit config.yaml with your settings
```

#### DNS Configuration

DNS is optional and can be configured in `config.yaml`:

```yaml
dns:
  enabled: true  # Set to false to use IP addresses only
  domain: "example.com"  # Your domain name
  app_name: "lablink"  # Application name for subdomains
  pattern: "auto"  # DNS naming pattern
```

**DNS Patterns:**

- **`auto`** (recommended): Environment-based subdomain
  - Production: `lablink.example.com`
  - Test: `test.lablink.example.com`
  - Dev: `dev.lablink.example.com`

- **`app-only`**: Same subdomain for all environments
  - All environments: `lablink.example.com`

- **`custom`**: Use custom subdomain
  - Set `custom_subdomain: "my-custom.example.com"`

**To disable DNS:** Set `enabled: false` or leave `domain` empty. The allocator will use IP addresses only.

## Deployment

### Local Development

```bash
cd lablink-allocator/lablink-allocator-service
uv run python main.py
```

### Production Deployment

See the [GitHub Actions workflows](.github/workflows/) for CI/CD deployment examples.

## Documentation

For comprehensive documentation, see:
- [Configuration Examples](lablink-allocator/lablink-allocator-service/conf/config.yaml.example)
- [Developer Guide](https://github.com/talmolab/lablink)

## License

[Add your license here]