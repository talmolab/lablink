# LabLink CLI

Command-line tool for deploying and managing LabLink teaching lab infrastructure —
on AWS (EC2 via Terraform) or on a machine you already have (`provider: manual`,
deployed with docker-compose).

## Installation

This package is not yet published to PyPI. Install it from source — the repo is a
`uv` workspace, so sync all three packages into the shared root venv:

```bash
git clone https://github.com/talmolab/lablink.git
cd lablink
uv sync --all-packages
source .venv/bin/activate
```

## Usage

```bash
lablink --help
lablink --version   # or -v
```

### Commands

| Command | Description |
|---------|-------------|
| `configure` | Create or edit LabLink configuration (interactive TUI) |
| `setup` | Provision provider-specific bootstrap resources (AWS: S3 + DynamoDB for Terraform state) |
| `doctor` | Check prerequisites and configuration |
| `deploy` | Deploy LabLink infrastructure (AWS Terraform or docker-compose) |
| `destroy` | Tear down LabLink infrastructure |
| `status` | Show deployment health and inventory |
| `logs` | View allocator and client logs |
| `export-metrics` | Export deployment metrics to CSV or JSON |
| `stats` | Show a cohort session-metrics summary in the terminal |
| `cleanup` | Remove deployment resources and local state |
| `show-config` | View the current LabLink configuration |
| `cache-clear` | Clear LabLink caches (Terraform templates, deployment metrics) |

### Client fleet commands

| Command | Description |
|---------|-------------|
| `client launch` | Launch client VMs via the allocator service (AWS provider) |
| `client register` | Register this bring-your-own box as a manual client and run the client container |
| `client unregister` | Tear down a registered BYO box |
| `client reset-overlay` | Discard this box's persisted mesh-overlay node identity |

Run `lablink <command> --help` for details on any command.

## Documentation

Full CLI documentation: https://talmolab.github.io/lablink/cli/
