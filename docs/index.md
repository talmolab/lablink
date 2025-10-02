# LabLink

LabLink allocates virtual machines (VMs) on Amazon Web Services (AWS) to make research software easily accessible. It’s designed to handle concurrent users and scale automatically. We maintain the infrastructure, Python packages, and Docker images—so you can focus on deploying any research software you need, on as many virtual machines as you want.

## Components

**Allocator** - Flask web service managing VM allocation and PostgreSQL database tracking VM states.

**Client VMs** - EC2 instances running containerized research software, reporting health to allocator.

**Infrastructure** - Our template repository with configurable infrastructure using terraform.

## Getting started

- [Prerequisites](prerequisites.md) - Prerequisites and setup
- [Quickstart](quickstart.md) - Deploy your first VM
- [Configuration](configuration.md) - Customize settings

## Links

- [GitHub](https://github.com/talmolab/lablink)
- [Template](https://github.com/talmolab/lablink-template)
- [Issues](https://github.com/talmolab/lablink/issues)
- [Releases](https://github.com/talmolab/lablink/releases)