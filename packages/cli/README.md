# LabLink CLI

Command-line tool for deploying and managing LabLink teaching lab infrastructure on AWS.

## Installation

```bash
uv tool install lablink-cli
```

This installs `lablink` as a global command in an isolated environment. See the [uv docs](https://docs.astral.sh/uv/guides/tools/) for more on `uv tool`.

## Usage

```bash
lablink --help
lablink --version   # or -v
```

### Commands

| Command | Description |
|---------|-------------|
| `configure` | Create or edit LabLink configuration (interactive TUI) |
| `setup` | Create S3 + DynamoDB resources for remote Terraform state |
| `deploy` | Deploy LabLink infrastructure with Terraform |
| `destroy` | Tear down LabLink infrastructure |
| `launch-client` | Launch client VMs via the allocator service |
| `status` | Health checks, Terraform state, and cost estimate |
| `logs` | View VM logs in an interactive TUI |
| `cleanup` | Clean up orphaned AWS resources and local state |
| `doctor` | Check prerequisites and configuration |
| `show-config` | View the current LabLink configuration |
| `cache-clear` | Clear LabLink caches (Terraform templates, deployment metrics) |
| `export-metrics` | Export deployment metrics to CSV or JSON |

Run `lablink <command> --help` for details on any command.

## Documentation

Full CLI documentation: https://talmolab.github.io/lablink/cli/
