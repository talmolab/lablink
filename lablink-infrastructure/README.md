# LabLink Infrastructure

Deploy your own LabLink VM allocation system for computational research workflows.

## Quick Start

### Prerequisites
- AWS account with credentials
- Terraform installed (v1.4+)
- Docker images published to GHCR (or use public ones)

### 1. Configure

```bash
# Copy example configs
cp config/example.config.yaml config/config.yaml
cp config/example.env .env
```

**Edit `config/config.yaml`:**
- Set `bucket_name` to a globally unique S3 bucket name
- Change `db.password` and `app.admin_password`
- Customize machine type, AMI, repository, region

**Edit `.env`:**
- Set your AWS credentials

### 2. Deploy Infrastructure

```bash
# Initialize Terraform (reads bucket_name from config/config.yaml)
./init-terraform.sh dev   # Local state, no S3
./init-terraform.sh test  # S3 backend with bucket from config
./init-terraform.sh prod  # S3 backend with bucket from config

# Or manually:
# terraform init -backend-config=backend-dev.hcl
# terraform init -backend-config=backend-test.hcl -backend-config="bucket=YOUR-BUCKET-NAME"

# Review and apply
terraform plan
terraform apply
```

### 3. Access Your Allocator

Once deployed, access the allocator web UI at the output IP address.

## What This Deploys

- **Allocator EC2 Instance**: Runs Flask app + PostgreSQL
- **Lambda Function**: Processes CloudWatch logs from client VMs
- **Security Groups**: Network configuration
- **IAM Roles**: Permissions for CloudWatch logging

## Configuration

### Key Settings in `config.yaml`

```yaml
db:
  password: "YOUR-DB-PASSWORD"  # Change this!

machine:
  machine_type: "g4dn.xlarge"  # Client VM instance type
  image: "ghcr.io/talmolab/lablink-client-base-image:0.0.8a0"
  ami_id: "ami-067cc81f948e50e06"  # Ubuntu AMI for your region
  repository: "https://github.com/yourusername/your-repo.git"

app:
  admin_password: "YOUR-ADMIN-PASSWORD"  # Change this!
  region: "us-west-2"

bucket_name: "your-unique-terraform-state-bucket"  # For test/prod
```

## Environments

- **dev**: Local state (`backend-dev.hcl`), no S3 needed
- **test**: S3 state (`backend-test.hcl`), uses `bucket_name` from config
- **prod**: S3 state (`backend-prod.hcl`), uses `bucket_name` from config

## Using Custom Docker Images

### Option 1: Use Pre-built Images
```yaml
image: "ghcr.io/talmolab/lablink-client-base-image:0.0.8a0"
```

### Option 2: Build Your Own
Fork [lablink repository](https://github.com/talmolab/lablink), customize packages, and build your own images.

## Documentation

Full documentation: https://talmolab.github.io/lablink/

- [Getting Started](https://talmolab.github.io/lablink/getting-started/)
- [Configuration Guide](https://talmolab.github.io/lablink/configuration/)
- [Architecture](https://talmolab.github.io/lablink/architecture/)
- [Troubleshooting](https://talmolab.github.io/lablink/troubleshooting/)

## Customization

### Different AWS Region
1. Update `app.region` in `config.yaml`
2. Find Ubuntu 22.04 AMI for your region
3. Update `machine.ami_id` in `config.yaml`

### Custom Software/Workflows
1. Build custom client Docker image
2. Publish to container registry (GHCR, ECR, Docker Hub)
3. Update `machine.image` in `config.yaml`

## Security Best Practices

- Change default passwords immediately
- Use IAM roles instead of access keys when possible
- Enable S3 backend encryption for production
- Restrict security group ingress rules
- Rotate SSH keys regularly

## Cleanup

```bash
terraform destroy
```

This deletes all resources (allocator EC2, Lambda, security groups, etc.).

## License

MIT License - see LICENSE file

## Contributing

Issues and contributions welcome at [talmolab/lablink](https://github.com/talmolab/lablink)
