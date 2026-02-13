# Prerequisites

Before deploying LabLink, you'll need to set up several tools and accounts. This guide covers everything you need to get started.

## Required Tools

### 1. AWS Account

You'll need an AWS account with appropriate permissions to create:

- EC2 instances
- Security groups
- Elastic IPs
- S3 buckets (for Terraform state)
- IAM roles and policies

**Cost Considerations**: See the [Cost Estimation](cost-estimation.md) guide for expected AWS costs.

### 2. AWS CLI

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

### 3. GitHub CLI (`gh`)

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

### 4. Git

Git should already be installed on most systems. Verify:
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

## Optional Tools

These tools are only needed for local development, debugging, or advanced workflows.

### Terraform

Only needed if you want to run Terraform locally (e.g., for debugging or manual deployments). The automated setup and GitHub Actions workflows handle Terraform for you.

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

### Docker

Only needed for local testing and development of LabLink services.

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

### Python and uv

If you want to run the services locally or contribute to development:

```bash
# Install uv (recommended Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Python 3.9+
uv python install 3.11
```

## Next Steps

Once you have the required tools installed:

1. [**Quickstart**](quickstart.md): Deploy LabLink to AWS using the automated setup scripts
2. [**AWS Setup (Manual)**](aws-setup.md): Reference guide for creating AWS resources individually