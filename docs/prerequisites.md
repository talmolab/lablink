# Prerequisites

What you need depends on which deployment path you take. **An AWS account, the AWS CLI, Terraform, and the GitHub CLI are not universal requirements** — the manual provider runs the allocator and its clients on hardware you already own, with none of them.

## Pick your path first

| Path | AWS account | Terraform | Docker | `gh` |
|---|---|---|---|---|
| [**CLI, manual provider**](cli/byo-clients.md) — allocator and clients run as containers on machines you already have | No | No | **Yes** | No |
| [**CLI, AWS provider**](cli/first-deployment.md) — EC2 provisioned from your own machine | Yes | Yes | No | No |
| [**Template repo**](quickstart-template.md) — EC2 provisioned by GitHub Actions | Yes | No (CI runs it) | No | Yes |

Every path needs [Python and uv](#python-and-uv) plus [Git](#git) to install the CLI. Install only the rest of what your row calls for.

## Everyone

### Python and uv

The CLI is a Python package. `uv` manages both it and the Python it runs on.

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Python 3.10+
uv python install 3.11
```

### Git

Needed to clone the repo — the CLI is not on PyPI yet, so a source install is the only route. See [CLI: Installation](cli/installation.md).

```bash
git --version
```

If not installed:

=== "macOS"
    ```bash
    brew install git
    ```

=== "Linux"
    ```bash
    sudo apt-get install git  # Debian/Ubuntu
    sudo yum install git      # RHEL/CentOS
    ```

=== "Windows"
    Download from [git-scm.com](https://git-scm.com/download/win)

## Manual provider only

### Docker

The manual provider runs the allocator as a docker-compose stack, and each client box runs the client container. You need Docker **and the `docker compose` v2 plugin** on the allocator host and on every client machine.

=== "macOS"
    Download [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/)

=== "Linux"
    ```bash
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    ```

=== "Windows"
    Download [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/)

!!! tip "Docker Permissions (Linux)"
    If you encounter permission errors:
    ```bash
    sudo usermod -aG docker $USER
    newgrp docker
    ```

`lablink doctor` verifies the Docker side for you under this provider.

Docker is also useful on any path for local testing and development of LabLink services.

## AWS paths only

Skip this whole section if you're using the manual provider.

### AWS Account

You'll need an AWS account with appropriate permissions to create:

- EC2 instances
- Security groups
- Elastic IPs
- S3 buckets (for Terraform state)
- IAM roles and policies

**Cost Considerations**: See the [Cost Estimation](cost-estimation.md) guide for expected AWS costs.

### AWS CLI

Install the AWS Command Line Interface:

=== "macOS"
    ```bash
    brew install awscli
    ```

=== "Linux"
    ```bash
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
    unzip awscliv2.zip
    sudo ./aws/install
    ```

=== "Windows"
    Download and run the [AWS CLI MSI installer](https://awscli.amazonaws.com/AWSCLIV2.msi)

Verify installation:
```bash
aws --version
```

#### Configure AWS Credentials

You have two options:

**Option 1: AWS Access Keys (Local Development)**
```bash
aws configure
```

Enter your:

- AWS Access Key ID
- AWS Secret Access Key
- Default region (e.g., `us-west-2`)
- Default output format (`json`)

**Option 2: OIDC (GitHub Actions)**

For automated deployments, you'll configure OpenID Connect (OIDC) to allow GitHub Actions to assume an IAM role without storing credentials. See [AWS Setup from Scratch](aws-setup.md#step-4-github-actions-oidc-configuration) for details.

### Terraform

Required for the **CLI + AWS provider** path, which drives Terraform from your machine. Not needed for the template repo path — GitHub Actions runs Terraform there — and not needed at all for the manual provider.

=== "macOS"
    ```bash
    brew tap hashicorp/tap
    brew install hashicorp/tap/terraform
    ```

=== "Linux"
    ```bash
    wget https://releases.hashicorp.com/terraform/1.6.6/terraform_1.6.6_linux_amd64.zip
    unzip terraform_1.6.6_linux_amd64.zip
    sudo mv terraform /usr/local/bin/
    ```

=== "Windows"
    Download from [Terraform Downloads](https://www.terraform.io/downloads.html) and add to PATH

**Version Requirement**: LabLink uses Terraform 1.6.6 (as specified in the CI workflow).

## Template repo path only

### GitHub CLI (`gh`)

The GitHub CLI is used by the setup scripts to configure repository secrets automatically.

=== "macOS"
    ```bash
    brew install gh
    ```

=== "Linux"
    ```bash
    sudo apt install gh
    ```

=== "Windows"
    ```bash
    winget install GitHub.cli
    ```

Authenticate with GitHub:
```bash
gh auth login
```

Verify installation:
```bash
gh --version
```

## Next Steps

Once you have the tools your path calls for:

1. [**Quickstart**](quickstart.md): Pick a deployment path
2. [**Bring-Your-Own Clients**](cli/byo-clients.md): The manual provider, start to finish
3. [**AWS Setup (Manual)**](aws-setup.md): Reference guide for creating AWS resources individually
