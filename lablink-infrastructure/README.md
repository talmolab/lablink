# LabLink Infrastructure

Deploy your own LabLink VM allocation system for computational research workflows.

> **Note**: This directory will be moved to a separate template repository ([lablink-template](https://github.com/talmolab/lablink-template)) in the future. See [MIGRATION_PLAN.md](../MIGRATION_PLAN.md) for details.

## Quick Start

### Step 0: GitHub Secrets Setup (Required for GitHub Actions)

If you plan to deploy via GitHub Actions workflows, you must configure one repository secret:

1. **Go to your repository Settings** → Secrets and variables → Actions
2. **Click "New repository secret"**
3. **Add the following secret:**

   | Name | Value | Description |
   |------|-------|-------------|
   | `AWS_ROLE_ARN` | `arn:aws:iam::YOUR-ACCOUNT-ID:role/YOUR-ROLE-NAME` | IAM role ARN for OIDC authentication |

**How to create the AWS IAM role for OIDC:**

```bash
# 1. Create a trust policy file
cat > trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::YOUR-ACCOUNT-ID:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:YOUR-ORG/YOUR-REPO:*"
        }
      }
    }
  ]
}
EOF

# 2. Create the IAM role
aws iam create-role \
  --role-name github-actions-lablink-deploy \
  --assume-role-policy-document file://trust-policy.json

# 3. Attach required policies
aws iam attach-role-policy \
  --role-name github-actions-lablink-deploy \
  --policy-arn arn:aws:iam::aws:policy/PowerUserAccess

# 4. Get the role ARN (use this for AWS_ROLE_ARN secret)
aws iam get-role \
  --role-name github-actions-lablink-deploy \
  --query 'Role.Arn' \
  --output text
```

**Note:** If deploying locally with Terraform (not via GitHub Actions), you don't need this secret. Just configure AWS CLI credentials instead.

### Prerequisites
- AWS account with credentials configured
- Terraform installed (v1.6.6+) for local deployments
- Docker images available on GHCR (or use public LabLink images)
- GitHub repository secret `AWS_ROLE_ARN` configured (for GitHub Actions deployments)

### 1. Configure

```bash
# Copy example configuration
cp config/example.config.yaml config/config.yaml
```

**Edit `config/config.yaml`:**
- **REQUIRED**: Change `db.password` and `app.admin_password` (security!)
- **REQUIRED**: Set `bucket_name` to a globally unique S3 bucket name (for test/prod)
- Customize `machine.ami_id` for your AWS region
- Customize `machine.image` to use your Docker image or LabLink's public images
- Customize `machine.repository` to clone your research code
- Set `app.region` to your AWS region

**Example configuration:**
```yaml
db:
  password: "YOUR-SECURE-DB-PASSWORD"  # CHANGE THIS!

machine:
  machine_type: "g4dn.xlarge"
  image: "ghcr.io/talmolab/lablink-client-base-image:latest"
  ami_id: "ami-0601752c11b394251"  # Ubuntu 24.04 with Docker + Nvidia (us-west-2)
  repository: "https://github.com/talmolab/sleap-tutorial-data.git"
  software: "sleap"

app:
  admin_password: "YOUR-SECURE-ADMIN-PASSWORD"  # CHANGE THIS!
  region: "us-west-2"

bucket_name: "tf-state-lablink-yourname"  # Must be globally unique

dns:
  enabled: true
  terraform_managed: true
  domain: "lablink.yourdomain.com"
  zone_id: "Z..."  # Your Route 53 hosted zone ID

ssl:
  provider: "letsencrypt"  # or "cloudflare" or "none"
  email: "admin@yourdomain.com"
```

### 2. Deploy Infrastructure

**Option A: Using helper script (recommended for first-time setup)**

```bash
# Initialize Terraform with automatic bucket configuration
./init-terraform.sh dev   # Local state, no S3
./init-terraform.sh test  # S3 backend, reads bucket from config.yaml
./init-terraform.sh prod  # S3 backend, reads bucket from config.yaml

# Review changes
terraform plan

# Deploy
terraform apply
```

**Option B: Manual Terraform commands**

```bash
# For dev (local state)
terraform init -backend-config=backend-dev.hcl

# For test/prod (S3 state)
terraform init -backend-config=backend-test.hcl -backend-config="bucket=YOUR-BUCKET-NAME"

# Review and apply
terraform plan
terraform apply
```

### 3. Verify Deployment (Optional)

After deployment completes, you can verify everything is working:

```bash
# Get outputs from Terraform
DOMAIN=$(terraform output -raw allocator_fqdn)
IP=$(terraform output -raw ec2_public_ip)

# Run verification script
./verify-deployment.sh "$DOMAIN" "$IP"
```

The verification script checks:
- DNS resolution (if domain configured)
- HTTP connectivity
- HTTPS/SSL certificate (if Let's Encrypt enabled)

### 4. Access Your Allocator

**With DNS configured:**
```
Allocator: https://lablink.yourdomain.com
Admin UI:  https://lablink.yourdomain.com/admin
```

**Without DNS (IP-only):**
```
Allocator: http://<ec2-public-ip>:5000
Admin UI:  http://<ec2-public-ip>:5000/admin
```

## What This Deploys

- **Allocator EC2 Instance**: Runs LabLink allocator service (Flask app + PostgreSQL in Docker)
- **Caddy Server**: Automatic HTTPS with Let's Encrypt SSL certificates
- **Lambda Function**: Processes CloudWatch logs from client VMs
- **Route 53 DNS**: Automatic DNS record management (if configured)
- **Security Groups**: Network security rules
- **IAM Roles**: Permissions for EC2 and CloudWatch logging
- **CloudWatch Log Groups**: Centralized logging for troubleshooting

## Environments

LabLink supports three deployment environments:

| Environment | Backend State | Use Case | S3 Bucket Required? |
|-------------|---------------|----------|---------------------|
| `dev`       | Local file    | Local testing, experimentation | No |
| `test`      | S3            | Staging, pre-production testing | Yes |
| `prod`      | S3            | Production deployments | Yes |

Each environment maintains separate Terraform state to avoid conflicts.

## Configuration Reference

### Database (`db`)
- `password`: PostgreSQL password (**CHANGE THIS!**)
- `dbname`: Database name (default: `lablink_db`)
- `user`: Database username (default: `lablink`)

### Machine Settings (`machine`)
- `machine_type`: AWS EC2 instance type for client VMs (e.g., `g4dn.xlarge`, `g5.2xlarge`)
- `image`: Docker image for client container (e.g., `ghcr.io/talmolab/lablink-client-base-image:latest`)
- `ami_id`: Amazon Machine Image for client VMs (region-specific)
- `repository`: Git repository to clone on client VMs (optional)
- `software`: Software identifier (e.g., `sleap`)

### Application (`app`)
- `admin_password`: Admin UI password (**CHANGE THIS!**)
- `admin_user`: Admin username (default: `admin`)
- `region`: AWS region (e.g., `us-west-2`)

### DNS Configuration (`dns`)
- `enabled`: Enable DNS management (true/false)
- `terraform_managed`: Let Terraform manage Route 53 records (true/false)
- `domain`: Your domain name (e.g., `lablink.example.com`)
- `zone_id`: Route 53 hosted zone ID (required if `terraform_managed: true`)

### SSL Configuration (`ssl`)
- `provider`: SSL provider (`letsencrypt`, `cloudflare`, or `none`)
- `email`: Email for Let's Encrypt notifications

### Terraform State (`bucket_name`)
- S3 bucket name for Terraform state storage (test/prod only)
- Must be globally unique

## Included Scripts

### `init-terraform.sh` (Optional Helper)
Simplifies Terraform initialization by automatically reading the S3 bucket name from your config file.

**Usage:**
```bash
./init-terraform.sh [dev|test|prod]
```

**What it does:**
- Reads `bucket_name` from `config/config.yaml`
- Runs `terraform init` with appropriate backend configuration
- Validates configuration before initializing

**Equivalent manual command:**
```bash
terraform init -backend-config=backend-test.hcl -backend-config="bucket=YOUR-BUCKET"
```

### `verify-deployment.sh` (Optional Manual Verification)
Comprehensive deployment verification script for post-deployment testing.

**Usage:**
```bash
./verify-deployment.sh [domain] [ip]

# Examples:
./verify-deployment.sh test.lablink.sleap.ai 52.10.119.234
./verify-deployment.sh "" 52.10.119.234  # IP-only deployment
```

**What it checks:**
1. DNS resolution (waits up to 5 minutes for propagation)
2. HTTP connectivity (waits for allocator to start)
3. HTTPS/SSL certificate (waits for Let's Encrypt, if enabled)

**When to use:**
- After first deployment to verify everything works
- When troubleshooting DNS or SSL issues
- To confirm HTTPS certificate was obtained

**Note:** GitHub Actions workflows include automatic verification, so this script is mainly for local deployments or manual troubleshooting.

### `user_data.sh` (Automatic - DO NOT RUN MANUALLY)
EC2 instance initialization script embedded in Terraform configuration.

**What it does:**
- Installs Docker and Caddy on the allocator EC2 instance
- Pulls the allocator Docker image
- Starts the allocator container
- Configures Caddy for SSL termination

**Note:** This script runs automatically when the EC2 instance boots. You never need to run it manually.

## AWS Region Configuration

AMI IDs are region-specific. If deploying to a different region:

1. Update `app.region` in `config/config.yaml`
2. Find the appropriate AMI for your region:
   ```bash
   # Ubuntu 24.04 with Docker + Nvidia GPU drivers
   aws ec2 describe-images \
     --region YOUR-REGION \
     --owners 099720109477 \
     --filters "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*" \
     --query 'Images | sort_by(@, &CreationDate) | [-1].[ImageId,Name]'
   ```
3. Update `machine.ami_id` in `config/config.yaml`

**Pre-configured custom AMIs (us-west-2):**
- Client VM: `ami-0601752c11b394251` (Ubuntu 24.04 + Docker + Nvidia GPU drivers)
- Allocator VM: `ami-0bd08c9d4aa9f0bc6` (Ubuntu 24.04 + Docker)

## Using Custom Docker Images

### Option 1: Use LabLink Public Images
```yaml
machine:
  image: "ghcr.io/talmolab/lablink-client-base-image:latest"
```

**Available tags:**
- `latest` - Latest stable release
- `linux-amd64-test` - Latest development build
- `0.0.8a0` - Specific version tag

### Option 2: Build Your Own Images
1. Fork the [LabLink repository](https://github.com/talmolab/lablink)
2. Customize the client package in `packages/client/`
3. Build and publish your images via GitHub Actions
4. Update `machine.image` in your config to use your custom image

## GitHub Actions Deployment

This infrastructure can be deployed via GitHub Actions workflows:

- **Deploy**: `.github/workflows/lablink-allocator-terraform.yml`
- **Destroy**: `.github/workflows/lablink-allocator-destroy.yml`

See the workflows in the `.github` directory for automated deployment examples.

## Security Best Practices

- ✅ **Change default passwords** in `config.yaml` before deploying
- ✅ Use **IAM roles** instead of access keys when possible
- ✅ Enable **S3 backend encryption** for production state files
- ✅ **Restrict security group** ingress rules to trusted IPs
- ✅ **Rotate SSH keys** regularly (every 90 days recommended)
- ✅ Use **separate environments** (dev/test/prod) with different credentials
- ✅ Enable **MFA** on AWS accounts with production access

## Troubleshooting

### Common Issues

**DNS not resolving:**
- Check Route 53 hosted zone exists and `zone_id` is correct
- Wait up to 5 minutes for DNS propagation
- Verify domain registrar nameservers point to Route 53

**SSL certificate not obtained:**
- Check DNS resolves correctly first (SSL requires valid DNS)
- Verify port 80 and 443 are accessible (Let's Encrypt validation)
- Check Caddy logs: `ssh ubuntu@<ip> sudo journalctl -u caddy -f`

**Allocator not responding:**
- Check Docker container is running: `ssh ubuntu@<ip> sudo docker ps`
- View container logs: `ssh ubuntu@<ip> sudo docker logs $(sudo docker ps -q)`
- Verify security group allows inbound traffic on port 5000

**Terraform state locked:**
- Check DynamoDB lock table in AWS console
- Manually remove lock if workflow was interrupted
- Use `terraform force-unlock <lock-id>` as last resort

### Getting Help

- **Documentation**: https://talmolab.github.io/lablink/
- **Issues**: https://github.com/talmolab/lablink/issues
- **Troubleshooting Guide**: https://talmolab.github.io/lablink/troubleshooting/

## Cleanup

To destroy all infrastructure:

```bash
terraform destroy
```

This removes:
- Allocator EC2 instance
- Lambda function
- Security groups
- Route 53 DNS records (if managed by Terraform)
- CloudWatch log groups
- IAM roles and policies

**Note:** The S3 bucket for Terraform state is NOT deleted automatically. Delete it manually if no longer needed.

## Documentation

Full documentation available at: https://talmolab.github.io/lablink/

- [Quickstart Guide](https://talmolab.github.io/lablink/quickstart/)
- [Configuration Reference](https://talmolab.github.io/lablink/configuration/)
- [Architecture Overview](https://talmolab.github.io/lablink/architecture/)
- [Deployment Guide](https://talmolab.github.io/lablink/deployment/)
- [DNS Configuration](https://talmolab.github.io/lablink/dns-configuration/)
- [Troubleshooting](https://talmolab.github.io/lablink/troubleshooting/)

## Contributing

Issues and contributions welcome at [talmolab/lablink](https://github.com/talmolab/lablink)

See [CONTRIBUTING.md](../docs/contributing.md) for development guidelines.

## License

BSD-3-Clause License - see [LICENSE](../LICENSE) file
