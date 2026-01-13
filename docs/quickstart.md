# Quickstart

Get LabLink running in 15 minutes.

!!! tip "Recommended: GitHub Actions Deployment"
    For production deployments, we recommend using GitHub Actions. See the [Deployment Guide](deployment.md) for the full workflow with automated CI/CD.

    This quickstart covers **local deployment** for testing and development.

## Prerequisites

- **AWS Account** with admin access ([setup guide](prerequisites.md#1-aws-account))
- **AWS CLI** configured locally ([setup guide](prerequisites.md#2-aws-cli))
- **Terraform** installed ([setup guide](prerequisites.md#3-terraform))
- **S3 Bucket** for Terraform state ([setup guide](aws-setup.md#step-2-s3-bucket-for-terraform-state))

## Step 1: Create Your Repository

Click the **"Use this template"** button on the [lablink-template repository](https://github.com/talmolab/lablink-template) to create your own deployment repository.

Then clone your new repository:

```bash
git clone https://github.com/YOUR_ORG/YOUR_REPO.git
cd YOUR_REPO/lablink-infrastructure
```

## Step 2: Configure Settings

Edit `config/config.yaml`:

```yaml
# Minimal configuration for quick start
dns:
  enabled: false  # Start without DNS, use IP address

ssl:
  provider: "none"  # Start without HTTPS

machine:
  ami_id: "ami-067cc81f948e50e06"  # Ubuntu 22.04 LTS (us-west-2)
  machine_type: "t3.medium"
  gpu_support: false
```

**Note on SSL**: This configuration uses `provider: "none"` for simplicity. For testing with DNS, you can use:
```yaml
ssl:
  provider: "letsencrypt"
  email: "your-email@example.com"
  staging: true  # HTTP only, unlimited deployments
```

Staging mode serves HTTP only. Your browser will show "Not Secure" - this is expected for testing. For production with HTTPS, set `staging: false`. See [Configuration - SSL Options](configuration.md#ssltls-options-ssl).

**Set passwords** in `config/config.yaml`:

```yaml
app:
  admin_password: "your-secure-admin-password"  # Replace placeholder

db:
  password: "your-secure-db-password"  # Replace placeholder
```

!!! warning "For GitHub Actions Deployment"
    When using GitHub Actions, set `ADMIN_PASSWORD` and `DB_PASSWORD` as repository secrets instead of editing the config file directly. See [AWS Setup - Add GitHub Secrets](aws-setup.md#46-add-github-secrets).

## Step 3: Initialize and Deploy

```bash
# Initialize Terraform with backend configuration
../scripts/init-terraform.sh test

# Deploy (will prompt for confirmation)
terraform apply -var="resource_suffix=test"
```

**Deployment time**: ~5 minutes

Creates:
- EC2 instance running allocator (Flask app + PostgreSQL)
- Security groups (HTTP port 80, SSH port 22)
- SSH key pair

## Step 4: Access Your Allocator

```bash
# Get public IP
terraform output ec2_public_ip
# Output: 52.10.123.456

# Save SSH key
terraform output -raw private_key_pem > ~/lablink-key.pem
chmod 600 ~/lablink-key.pem
```

**Web interface**: `http://<ec2_public_ip>`

**Admin login**:

- Username: `admin`
- Password: The password you set in Step 2

## Step 5: Create Client VMs

1. Navigate to `http://<ec2_public_ip>/admin`
2. Log in with admin credentials
3. Click **"Create VMs"**
4. Enter number of VMs (try 2)
5. Click **"Launch VMs"**

**VM creation time**: ~5 minutes

## Step 6: Verify

```bash
# SSH into allocator
ssh -i ~/lablink-key.pem ubuntu@<ec2_public_ip>

# Check allocator is running
sudo docker ps

# Check VMs in database
sudo docker exec $(sudo docker ps -q) psql -U lablink -d lablink_db -c "SELECT hostname FROM vms;"
```

## Step 7: Cleanup

```bash
# Destroy all resources
terraform destroy -var="resource_suffix=test"
```

!!! warning "AWS Costs"
    EC2 instances cost ~$0.04/hour (t3.medium). Always destroy test resources.

## Troubleshooting

**Can't access web interface?**
```bash
curl http://$(terraform output -raw ec2_public_ip)
# If this fails, check security group allows port 80
```

**VMs not appearing?** See [VM Registration Issue](troubleshooting.md#client-vm-not-registering)

**SSH permission denied?**
```bash
chmod 600 ~/lablink-key.pem
```

## Next Steps

- **GitHub Actions**: [Deployment Guide](deployment.md) for automated CI/CD deployments (recommended for production)
- **AWS Setup**: [AWS Setup Guide](aws-setup.md) for IAM roles, OIDC, and GitHub secrets
- **Add DNS**: [DNS Configuration Guide](dns-configuration.md) for custom domains and HTTPS
- **Customize**: [Configuration Reference](configuration.md) for all options
- **Secure**: [Security Guide](security.md) before going to production
