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

### 3. Terraform

Install Terraform for infrastructure provisioning:

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

Verify installation:
```bash
terraform version
```

**Version Requirement**: LabLink uses Terraform 1.6.6 (as specified in the CI workflow).

### 4. Docker

Install Docker for local testing and development:

=== "macOS"
    Download [Docker Desktop for Mac](https://docs.docker.com/desktop/install/mac-install/)

=== "Linux"
    ```bash
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    ```

=== "Windows"
    Download [Docker Desktop for Windows](https://docs.docker.com/desktop/install/windows-install/)

Verify installation:
```bash
docker --version
docker ps
```

!!! tip "Docker Permissions (Linux)"
    If you encounter permission errors:
    ```bash
    sudo usermod -aG docker $USER
    newgrp docker
    ```

### 5. Git

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

### GitHub CLI (gh)

Useful for managing releases and workflows:

```bash
# macOS
brew install gh

# Linux
sudo apt install gh

# Windows
winget install GitHub.cli
```

### Python and uv

If you want to run the services locally or contribute to development:

```bash
# Install uv (recommended Python package manager)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Python 3.9+
uv python install 3.11
```

## AWS Resource Requirements

Before deploying, ensure you have or will create:

1. **S3 Bucket**: For Terraform state storage
   - Naming: `tf-state-lablink-allocator-bucket` (configurable)
   - Versioning enabled recommended

2. **Elastic IPs**: Pre-allocated for each environment
   - 1 for dev
   - 1 for test
   - 1 for prod

3. **IAM Roles**: For OIDC authentication (GitHub Actions)
   - Trust relationship with GitHub
   - Permissions for EC2, S3, Route53

4. **Route 53 Hosted Zone** (Optional): For custom DNS
   - Example: `lablink.yourdomain.com`

See the [AWS Setup from Scratch](aws-setup.md) guide for detailed setup instructions.

## SSH Key Pair

LabLink automatically generates SSH key pairs via Terraform, but you should be familiar with:

- SSH key management
- File permissions (chmod 600)
- Connecting to EC2 instances via SSH

## Next Steps

Once you have these prerequisites installed:

1. [**Installation**](installation.md): Set up LabLink locally
2. [**AWS Setup**](aws-setup.md): Configure AWS resources from scratch
3. [**Configuration**](configuration.md): Customize LabLink for your needs