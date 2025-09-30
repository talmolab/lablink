# LabLink

[![CI](https://github.com/talmolab/lablink/actions/workflows/ci.yml/badge.svg)](https://github.com/talmolab/lablink/actions/workflows/ci.yml)
[![Docs](https://github.com/talmolab/lablink/actions/workflows/docs.yml/badge.svg)](https://talmolab.github.io/lablink/)
[![License](https://img.shields.io/github/license/talmolab/lablink)](LICENSE)

**Dynamic VM allocation and management system for computational research workflows.**

LabLink automates the deployment and management of cloud-based virtual machines for running research software at scale.

## Features

- 🚀 **Automated VM Management**: Dynamically provision and manage AWS EC2 instances
- 🐳 **Container-Based**: Run any research software via Docker
- ⚙️ **Easy Configuration**: YAML-based configuration for customization
- 🔄 **CI/CD Ready**: GitHub Actions workflows for automated deployment
- 🎯 **Research-Focused**: Built for SLEAP and other computational research tools
- 📊 **Web Dashboard**: Monitor and manage VMs via web interface
- 💰 **Cost-Effective**: Supports Spot Instances and auto-scaling

## Quick Start

### Prerequisites

- AWS account with appropriate permissions
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) installed and configured
- [Terraform](https://www.terraform.io/downloads) >= 1.6.6
- [Docker](https://docs.docker.com/get-docker/) installed and running

### Test Locally (5 minutes)

```bash
# Pull and run the allocator
docker pull ghcr.io/talmolab/lablink-allocator-image:latest
docker run -d -p 5000:5000 ghcr.io/talmolab/lablink-allocator-image:latest

# Access at http://localhost:5000
# Default credentials: admin / IwanttoSLEAP
```

### Deploy to AWS (10 minutes)

```bash
# Clone repository
git clone https://github.com/talmolab/lablink.git
cd lablink/lablink-allocator

# Initialize Terraform
terraform init

# Deploy allocator
terraform apply \
  -var="resource_suffix=dev" \
  -var="allocator_image_tag=linux-amd64-latest"

# Get allocator IP
terraform output ec2_public_ip

# Save SSH key
terraform output -raw private_key_pem > ~/lablink-dev-key.pem
chmod 600 ~/lablink-dev-key.pem
```

Access your allocator at `http://<ec2-ip>:80`

## Documentation

📚 **[Full Documentation](https://talmolab.github.io/lablink/)**

### Key Guides

- **[Prerequisites](https://talmolab.github.io/lablink/prerequisites/)** - AWS setup, tools installation
- **[Installation](https://talmolab.github.io/lablink/installation/)** - Detailed installation guide
- **[Quickstart](https://talmolab.github.io/lablink/quickstart/)** - Get up and running quickly
- **[Configuration](https://talmolab.github.io/lablink/configuration/)** - Customize LabLink
- **[Adapting LabLink](https://talmolab.github.io/lablink/adapting/)** - Use your own research software
- **[Deployment](https://talmolab.github.io/lablink/deployment/)** - Production deployment guide
- **[Troubleshooting](https://talmolab.github.io/lablink/troubleshooting/)** - Common issues and solutions

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         GitHub                               │
│  ┌────────────────┐      ┌──────────────────┐              │
│  │  Source Code   │──────│ GitHub Actions   │              │
│  └────────────────┘      └────────┬─────────┘              │
└────────────────────────────────────┼──────────────────────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │  Terraform + Docker Images      │
                    └────────────┬────────────────────┘
                                 │
┌────────────────────────────────┼─────────────────────────────┐
│                        AWS Cloud                             │
│                                                              │
│  ┌─────────────────────────────▼──────────────────────────┐ │
│  │              Allocator EC2 Instance                     │ │
│  │  ┌──────────────────────────────────────────────────┐  │ │
│  │  │  Flask App + PostgreSQL Database                 │  │ │
│  │  └──────────────────────────────────────────────────┘  │ │
│  └─────────────────────────────────────────────────────────┘ │
│                            │                                 │
│                            │ spawns                          │
│                            ▼                                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │          Client EC2 Instances (Dynamic)              │   │
│  │  - Run research workloads in Docker                  │   │
│  │  - GPU support (T4, A10G, V100)                      │   │
│  │  - Auto-report health status                         │   │
│  └──────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

## Configuration

Customize LabLink for your research software by editing `lablink-allocator/lablink-allocator-service/conf/config.yaml`:

```yaml
machine:
  machine_type: "g4dn.xlarge"  # GPU instance type
  image: "ghcr.io/your-org/your-research-image:latest"  # Your Docker image
  repository: "https://github.com/your-org/your-code.git"  # Your code repo
  software: "your-software-name"
```

See [Configuration Guide](https://talmolab.github.io/lablink/configuration/) for all options.

## Adapting for Your Research

LabLink is designed to be **software-agnostic**. While it ships with SLEAP support, you can adapt it for any computational workflow:

1. **Create Docker image** with your research software
2. **Update configuration** with your image and repository
3. **Deploy** to AWS

See [Adapting LabLink Guide](https://talmolab.github.io/lablink/adapting/) for step-by-step instructions.

## Use Cases

- 🧬 Running SLEAP pose estimation at scale
- 🤖 Training machine learning models on GPU instances
- 📊 Batch processing of computational workloads
- 🔬 Any containerized research software requiring cloud compute

## Cost Estimation

**Minimal setup**: ~$20/month
**Light production**: ~$481/month
**Heavy production**: ~$1,182/month (with Spot Instances)

See [Cost Estimation Guide](https://talmolab.github.io/lablink/cost-estimation/) for detailed breakdown and optimization tips.

## Development

### Local Setup

```bash
# Install uv (recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Setup allocator
cd lablink-allocator/lablink-allocator-service
uv sync --extra dev

# Run tests
PYTHONPATH=. pytest

# Run linting
ruff check .
```

### Building Documentation

**Using uv (Recommended):**

```bash
# Quick test (temporary environment)
uv run --extra docs mkdocs serve

# Or create persistent environment
uv venv .venv-docs
.venv-docs\Scripts\activate  # Windows
# source .venv-docs/bin/activate  # macOS/Linux
uv sync --extra docs
mkdocs serve
```

**Using pip:**

```bash
# Install dependencies
pip install -e ".[docs]"

# Serve locally
mkdocs serve

# Build
mkdocs build
```

See [Contributing to Documentation](https://talmolab.github.io/lablink/contributing-docs/) for more details.

## CI/CD

LabLink uses GitHub Actions for automated testing and deployment:

- **CI**: Runs tests and linting on every PR
- **Docker Images**: Builds and pushes to ghcr.io on push
- **Infrastructure**: Deploys to AWS via Terraform
- **Documentation**: Auto-deploys to GitHub Pages

See [Workflows Guide](https://talmolab.github.io/lablink/workflows/) for details.

## Security

- 🔐 **OIDC Authentication**: GitHub Actions authenticate to AWS without stored credentials
- 🔑 **SSH Key Management**: Auto-generated, ephemeral keys
- 🛡️ **Security Groups**: Network access control
- 🔒 **Encryption**: S3 state encryption, optional EBS encryption

**Important**: Change default passwords before production deployment!

See [Security Guide](https://talmolab.github.io/lablink/security/) for best practices.

## Troubleshooting

**PostgreSQL won't start?**
```bash
ssh -i ~/lablink-key.pem ubuntu@<allocator-ip>
sudo docker exec -it <container-id> /etc/init.d/postgresql restart
```

**Can't SSH?**
```bash
chmod 600 ~/lablink-key.pem
```

**VMs not being created?**
Check allocator logs:
```bash
sudo docker logs <container-id>
```

See [Troubleshooting Guide](https://talmolab.github.io/lablink/troubleshooting/) for more solutions.

## Support

- 📖 **Documentation**: https://talmolab.github.io/lablink/
- 🐛 **Bug Reports**: [GitHub Issues](https://github.com/talmolab/lablink/issues)
- 💬 **Discussions**: [GitHub Discussions](https://github.com/talmolab/lablink/discussions)
- 📧 **Email**: [Open an issue](https://github.com/talmolab/lablink/issues/new)

## Contributing

Contributions welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

**Quick start:**
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes and add tests
4. Update documentation
5. Submit a pull request

See also:
- [CONTRIBUTING.md](CONTRIBUTING.md) - Contribution guidelines
- [CLAUDE.md](CLAUDE.md) - Developer/AI assistant guidance
- [Contributing to Docs](https://talmolab.github.io/lablink/contributing-docs/) - Documentation guidelines

## License

This project is licensed under the BSD-3-Clause License - see the [LICENSE](LICENSE) file for details.

## Citation

If you use LabLink in your research, please cite:

```bibtex
@software{lablink2025,
  title = {LabLink: Dynamic VM Allocation for Computational Research},
  author = {Talmo Lab},
  year = {2025},
  url = {https://github.com/talmolab/lablink}
}
```

## Acknowledgments

- Built by the [Talmo Lab](https://talmolab.org/)
- Designed for [SLEAP](https://sleap.ai/) and the computational research community
- Inspired by the need for scalable, accessible cloud computing for science

## Related Projects

- [SLEAP](https://github.com/talmolab/sleap) - Multi-animal pose tracking
- [sleap-nn](https://github.com/talmolab/sleap-nn) - SLEAP neural network models

---

**Made with ❤️ by the Talmo Lab**