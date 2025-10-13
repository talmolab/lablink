# LabLink

Dynamic VM allocation system for computational research workflows. Deploy research software to AWS in minutes.

## Quick Start

**For Deployment**: Get running in 15 minutes using the [LabLink Template](https://github.com/talmolab/lablink-template)

```bash
git clone https://github.com/talmolab/lablink-template.git
cd lablink-template/lablink-infrastructure
terraform init && terraform apply
```

**For Development**: See the [Contributing Guide](contributing.md) to develop LabLink packages

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
