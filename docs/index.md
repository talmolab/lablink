# LabLink

Welcome to LabLink, a dynamic VM allocation and management system designed for computational research workflows.

## Overview

LabLink is a platform that simplifies the deployment and management of cloud-based virtual machines for research computing. It provides:

- **Dynamic VM Allocation**: Automatically provision and manage cloud VMs on demand
- **Flexible Configuration**: Easy customization for different research software and workflows
- **Infrastructure as Code**: Terraform-based deployment for reproducible infrastructure
- **Multi-Environment Support**: Separate dev, test, and production environments
- **Automated Workflows**: GitHub Actions CI/CD for seamless deployments

## Key Components

### Allocator Server
A Flask-based web application running on AWS EC2 that:

- Manages VM allocation requests
- Maintains a PostgreSQL database of VM states
- Provides web interface and API endpoints for VM management
- Handles authentication and authorization

### Client VMs
Dynamically spawned EC2 instances that:

- Run containerized research software
- Report health status to the allocator
- Auto-configure based on your research needs
- Support custom Docker images and repositories

### Infrastructure Management
- **Terraform**: Provisions and manages AWS infrastructure
- **GitHub Actions**: Automates building, testing, and deployment
- **Docker**: Containerizes both allocator and client services

## Design Philosophy

LabLink emphasizes **simplicity, extensibility, and automation**:

- Simple configuration through YAML files
- Extensible for different research software (SLEAP, custom tools, etc.)
- Automated deployment and management through CI/CD
- Secure by default with SSH key management and OIDC authentication

## Quick Links

- [**Get Started**](prerequisites.md): Prerequisites and installation
- [**Configuration**](configuration.md): Customize LabLink for your needs
- [**Deployment**](deployment.md): Deploy to AWS
- [**Troubleshooting**](troubleshooting.md): Common issues and solutions

## Use Cases

LabLink is ideal for:

- Research labs needing on-demand GPU compute resources
- Batch processing of computational workloads
- Training machine learning models on cloud infrastructure
- Running containerized research software at scale

## Support

- **Documentation**: You're reading it!
- **Issues**: [GitHub Issues](https://github.com/talmolab/lablink/issues)
- **Releases**: [GitHub Releases](https://github.com/talmolab/lablink/releases)

## License

LabLink is open source software. See the [LICENSE](https://github.com/talmolab/lablink/blob/main/LICENSE) file for details.