# LabLink

Dynamic VM allocation system for computational research workflows. Deploy research software to AWS in minutes.

## Quick Start

**For Deployment**: Deploy LabLink infrastructure to AWS in 15 minutes

Use the [LabLink Template Repository](https://github.com/talmolab/lablink-template) to deploy the allocator and client VMs:

```bash
# Clone the template repository
git clone https://github.com/talmolab/lablink-template.git
cd lablink-template/lablink-infrastructure

# Deploy infrastructure (requires AWS credentials)
terraform init && terraform apply
```

See the [Quickstart Guide](quickstart.md) for detailed deployment instructions.

**For Development**: Develop LabLink packages

This repository contains the Python packages and Docker images. See the [Contributing Guide](contributing.md) to develop packages locally.

## What is LabLink?

LabLink automatically provisions and manages cloud-based virtual machines for research software. It handles:

- **VM Allocation** - Request VMs through a web interface
- **Auto-scaling** - Create dozens of VMs in parallel
- **Health Monitoring** - Track VM status and GPU health
- **Custom Software** - Deploy any Docker image or GitHub repo

## Core Components

**Allocator** - Web service managing VM requests and database (Python package + Docker image)

**Client VMs** - EC2 instances running your research software (Python package + Docker image)

**Infrastructure** - Terraform templates for AWS deployment ([lablink-template](https://github.com/talmolab/lablink-template))

## Documentation

- [Prerequisites](prerequisites.md) - AWS account setup
- [Quickstart](quickstart.md) - Deploy in 15 minutes
- [Configuration](configuration.md) - Customize your deployment
- [Troubleshooting](troubleshooting.md) - Common issues and fixes

## Resources

- [GitHub](https://github.com/talmolab/lablink)
- [Template](https://github.com/talmolab/lablink-template)
- [Issues](https://github.com/talmolab/lablink/issues)
