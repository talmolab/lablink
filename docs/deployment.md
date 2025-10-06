# Deployment

This guide covers deploying LabLink to AWS using both automated (GitHub Actions) and manual (Terraform CLI) methods.

## Deployment Overview

LabLink supports three deployment environments:

| Environment | Purpose | Trigger | Image Tag |
|-------------|---------|---------|-----------|
| **dev** | Local/personal development | Manual | `*-test` |
| **test** | Staging, pre-production testing | Push to `test` branch | `*-test` |
| **prod** | Production workloads | Manual workflow dispatch | Pinned version tags |

## Prerequisites

Before deploying, ensure you have:

- [x] AWS account configured (see [Prerequisites](prerequisites.md#1-aws-account))
- [x] Terraform installed (see [Prerequisites](prerequisites.md#3-terraform))
- [x] S3 bucket for Terraform state (see [AWS Setup](aws-setup.md#step-2-s3-bucket-for-terraform-state))
- [x] Elastic IP allocated for test/prod (see [AWS Setup](aws-setup.md#step-3-elastic-ip-allocation))
- [x] IAM roles configured for GitHub Actions (see [AWS Setup](aws-setup.md#step-4-oidc-configuration))

## Method 1: GitHub Actions (Recommended)

Automated deployment via CI/CD pipelines.

### Initial Setup

1. **Configure GitHub Secrets**

   Navigate to **Settings → Secrets and variables → Actions** in your GitHub repository.

   Required secrets:
   - `AWS_ROLE_ARN`: IAM role ARN for GitHub Actions authentication
     Example: `arn:aws:iam::711387140753:role/GitHubActionsLabLinkRole`
   - `AWS_REGION`: AWS region for deployment
     Example: `us-west-2`, `eu-west-1`, `ap-northeast-1`
     **Note:** Must match region in `config/config.yaml`

   Optional secrets:
   - `ADMIN_PASSWORD`: Override default admin password
   - `DB_PASSWORD`: Override default database password

2. **Verify OIDC Configuration**

   Ensure AWS IAM role exists and trusts your GitHub repository:

   - OIDC provider exists: `token.actions.githubusercontent.com`
   - IAM role trust policy includes your repository: `repo:YOUR_ORG/YOUR_REPO:*`
   - Role has PowerUserAccess or equivalent permissions

   See detailed setup instructions: [AWS Setup → OIDC Configuration](aws-setup.md#step-4-github-actions-oidc-configuration)

### Deploy to Test Environment

**Trigger**: Push to `test` branch

```bash
git checkout -b test
git push origin test
```

This automatically:
1. Builds Docker images with `-test` tags
2. Runs Terraform init with `backend-test.hcl`
3. Deploys to test environment
4. Outputs allocator URL and SSH key

**Monitor Progress**:
- Go to **Actions** tab in GitHub
- Watch `Terraform Deploy` workflow
- Check logs for any errors

**Access Deployment**:
- Allocator URL: Available in workflow output
- SSH Key: Download from workflow artifacts

### Deploy to Production

**Trigger**: Manual workflow dispatch

1. **Navigate to Actions tab** in GitHub

2. **Select "Terraform Deploy" workflow**

3. **Click "Run workflow"**

4. **Fill in parameters**:
   - **Environment**: `prod`
   - **Image tag**: Specific version (e.g., `v1.0.0` or commit SHA)

5. **Click "Run workflow"**

**Why Manual?**
Production deployments use pinned image tags for reproducibility and require explicit approval.

!!! warning "Production Image Tags"
    Never use `:latest` or `-test` tags in production. Always use specific version tags or commit SHAs.

### Deployment Outputs

After successful deployment, the workflow provides:

- **Allocator FQDN**: DNS name for your allocator
- **EC2 Public IP**: IP address of the allocator instance
- **EC2 Key Name**: Name of the SSH key pair
- **Private Key**: Downloaded as artifact (expires in 1 day)

### Deployment Workflow Details

The GitHub Actions workflow (`.github/workflows/lablink-allocator-terraform.yml`) performs:

1. **Checkout code** from repository
2. **Configure AWS credentials** via OIDC
3. **Setup Terraform** (version 1.6.6)
4. **Determine environment** from trigger
5. **Initialize Terraform** with environment-specific backend
6. **Validate** Terraform configuration
7. **Plan** infrastructure changes
8. **Apply** changes to AWS
9. **Save SSH key** as artifact
10. **Output** deployment details
11. **Destroy on failure** (if apply fails)

## Method 2: Manual Terraform Deployment

Deploy directly from your local machine using Terraform CLI.

### Step 1: Clone Repository

```bash
git clone https://github.com/talmolab/lablink.git
cd lablink/lablink-infrastructure
```

### Step 2: Configure AWS Credentials

**Option A: AWS CLI Profiles**
```bash
export AWS_PROFILE=your-profile
aws configure --profile your-profile
```

**Option B: Environment Variables**
```bash
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_REGION=us-west-2
```

**Option C: AWS SSO**
```bash
aws sso login --profile your-sso-profile
export AWS_PROFILE=your-sso-profile
```

### Step 3: Initialize Terraform

**For dev environment (local state)**:
```bash
terraform init
```

**For test/prod (remote state)**:
```bash
# Test
terraform init -backend-config=backend-test.hcl

# Production
terraform init -backend-config=backend-prod.hcl
```

### Step 4: Plan Deployment

Preview infrastructure changes:

```bash
terraform plan \
  -var="resource_suffix=dev" \
  -var="allocator_image_tag=linux-amd64-latest-test"
```

Review the plan output carefully. Terraform will show:
- Resources to be created
- Resources to be modified
- Resources to be destroyed

### Step 5: Apply Deployment

Deploy the infrastructure:

```bash
terraform apply \
  -var="resource_suffix=dev" \
  -var="allocator_image_tag=linux-amd64-latest-test"
```

Type `yes` when prompted to confirm.

**Deployment time**: ~5-10 minutes

### Step 6: Get Outputs

After deployment completes:

```bash
# Get allocator URL
terraform output allocator_fqdn

# Get public IP
terraform output ec2_public_ip

# Save SSH key
terraform output -raw private_key_pem > ~/lablink-dev-key.pem
chmod 600 ~/lablink-dev-key.pem
```

### Step 7: Verify Deployment

Test the allocator:

```bash
# Get the IP
ALLOCATOR_IP=$(terraform output -raw ec2_public_ip)

# Test web interface
curl http://$ALLOCATOR_IP:80

# SSH into instance
ssh -i ~/lablink-dev-key.pem ubuntu@$ALLOCATOR_IP
```

## Terraform Variables

Key variables for customizing deployment:

| Variable | Description | Default | Example |
|----------|-------------|---------|---------|
| `resource_suffix` | Environment suffix for resource names | `dev` | `prod`, `test` |
| `allocator_image_tag` | Docker image tag for allocator | (required) | `v1.0.0`, `linux-amd64-latest-test` |
| `instance_type` | EC2 instance type for allocator | `t2.micro` | `t2.small`, `t3.medium` |
| `allocated_eip` | Pre-allocated Elastic IP (test/prod) | None | `eipalloc-xxxxx` |

**Usage**:
```bash
terraform apply \
  -var="resource_suffix=prod" \
  -var="allocator_image_tag=v1.0.0" \
  -var="instance_type=t2.small" \
  -var="allocated_eip=eipalloc-xxxxx"
```

## Environment-Specific Configurations

### Development

**Purpose**: Local testing, rapid iteration

**Configuration**:
- Terraform state: Local file
- Image tag: `-test` versions
- Instance type: `t2.micro` (cheapest)
- No Elastic IP (dynamic)

**Deploy**:
```bash
terraform init
terraform apply \
  -var="resource_suffix=dev" \
  -var="allocator_image_tag=linux-amd64-latest-test"
```

### Test/Staging

**Purpose**: Pre-production validation, integration testing

**Configuration**:
- Terraform state: S3 bucket (`backend-test.hcl`)
- Image tag: `-test` versions
- Instance type: Same as production
- Elastic IP: Pre-allocated

**Deploy**:
```bash
terraform init -backend-config=backend-test.hcl
terraform apply \
  -var="resource_suffix=test" \
  -var="allocator_image_tag=linux-amd64-latest-test" \
  -var="allocated_eip=eipalloc-test"
```

### Production

**Purpose**: Live workloads, stable releases

**Configuration**:
- Terraform state: S3 bucket (`backend-prod.hcl`)
- Image tag: Pinned versions (`v1.0.0`)
- Instance type: Appropriately sized
- Elastic IP: Pre-allocated
- Monitoring and backups enabled

**Deploy**:
```bash
terraform init -backend-config=backend-prod.hcl
terraform apply \
  -var="resource_suffix=prod" \
  -var="allocator_image_tag=v1.0.0" \
  -var="allocated_eip=eipalloc-prod"
```

## Post-Deployment Tasks

After deploying the allocator:

### 1. Configure DNS (Optional)

Point a custom domain to your allocator for easier access.

#### Using AWS Route 53

**Quick Update**:
```bash
# Get IP
ALLOCATOR_IP=$(terraform output -raw ec2_public_ip)

# Update Route 53 A record
aws route53 change-resource-record-sets \
  --hosted-zone-id Z1234567890ABC \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "lablink.yourdomain.com",
        "Type": "A",
        "TTL": 300,
        "ResourceRecords": [{"Value": "'$ALLOCATOR_IP'"}]
      }
    }]
  }'
```

#### Example: Talmo Lab DNS Configuration

The Talmo Lab LabLink deployment uses the `sleap.ai` domain with environment-specific subdomains:

| Environment | Subdomain | IP Address | Purpose |
|-------------|-----------|------------|---------|
| **Production** | `lablink.sleap.ai` | `44.247.165.126` | Production allocator |
| **Test** | `test.lablink.sleap.ai` | `100.20.149.17` | Testing environment |
| **Dev** | `dev.lablink.sleap.ai` | `34.208.206.60` | Development environment |

**DNS Configuration**:
- **Type**: A Records
- **TTL**: 300 seconds
- **Managed via**: AWS Route 53
- **Name Servers**:
  - `ns-158.awsdns-19.com`
  - `ns-697.awsdns-23.net`
  - `ns-1839.awsdns-37.co.uk`
  - `ns-1029.awsdns-00.org`

**To replicate this setup**:

1. **Create hosted zone** in Route 53:
   ```bash
   aws route53 create-hosted-zone \
     --name sleap.ai \
     --caller-reference $(date +%s)
   ```

2. **Add A records** for each environment:
   ```bash
   # Production
   aws route53 change-resource-record-sets \
     --hosted-zone-id YOUR_ZONE_ID \
     --change-batch '{
       "Changes": [{
         "Action": "UPSERT",
         "ResourceRecordSet": {
           "Name": "lablink.sleap.ai",
           "Type": "A",
           "TTL": 300,
           "ResourceRecords": [{"Value": "44.247.165.126"}]
         }
       }]
     }'

   # Test environment
   aws route53 change-resource-record-sets \
     --hosted-zone-id YOUR_ZONE_ID \
     --change-batch '{
       "Changes": [{
         "Action": "UPSERT",
         "ResourceRecordSet": {
           "Name": "test.lablink.sleap.ai",
           "Type": "A",
           "TTL": 300,
           "ResourceRecords": [{"Value": "100.20.149.17"}]
         }
       }]
     }'

   # Dev environment
   aws route53 change-resource-record-sets \
     --hosted-zone-id YOUR_ZONE_ID \
     --change-batch '{
       "Changes": [{
         "Action": "UPSERT",
         "ResourceRecordSet": {
           "Name": "dev.lablink.sleap.ai",
           "Type": "A",
           "TTL": 300,
           "ResourceRecords": [{"Value": "34.208.206.60"}]
         }
       }]
     }'
   ```

3. **Verify DNS propagation**:
   ```bash
   # Check if DNS is resolving
   nslookup lablink.sleap.ai
   dig lablink.sleap.ai

   # Test all environments
   curl http://lablink.sleap.ai
   curl http://test.lablink.sleap.ai
   curl http://dev.lablink.sleap.ai
   ```

!!! tip "DNS Best Practices"
    - Use environment-specific subdomains (e.g., `prod.`, `test.`, `dev.`)
    - Keep TTL low (300s) for easier updates during initial setup
    - Increase TTL (3600s+) once stable to reduce DNS query costs
    - Use Elastic IPs for production to avoid DNS updates on instance replacement

### 2. Change Default Passwords

!!! danger "Security Critical"
    Change default passwords before creating any VMs!

SSH into allocator and update configuration:
```bash
ssh -i ~/lablink-key.pem ubuntu@$ALLOCATOR_IP
sudo docker exec -it <container> bash
# Edit config and restart container
```

See [Security → Change Default Passwords](security.md#change-default-passwords).

### 3. Test VM Creation

Via web interface:
1. Navigate to `http://<allocator-ip>:80`
2. Login with admin credentials
3. Go to **Admin → Create Instances**
4. Enter number of VMs to create
5. Submit and monitor creation

Via API:
```bash
curl -X POST http://<allocator-ip>:80/request_vm \
  -d "email=test@example.com" \
  -d "crd_command=test_command"
```

### 4. Monitor Logs

```bash
# SSH into allocator
ssh -i ~/lablink-key.pem ubuntu@$ALLOCATOR_IP

# Check Docker containers
sudo docker ps

# View allocator logs
sudo docker logs <allocator-container-id>

# View PostgreSQL logs
sudo docker exec -it <allocator-container-id> \
  tail -f /var/log/postgresql/postgresql-13-main.log
```

## Updating a Deployment

To update an existing deployment with new configuration or image:

```bash
# Pull latest code
git pull origin main

# Re-initialize if needed
terraform init -reconfigure

# Plan changes
terraform plan \
  -var="resource_suffix=dev" \
  -var="allocator_image_tag=new-version"

# Apply changes
terraform apply \
  -var="resource_suffix=dev" \
  -var="allocator_image_tag=new-version"
```

**Note**: Changing the image tag will replace the EC2 instance.

## Destroying a Deployment

### Via GitHub Actions

Use the destroy workflow:

1. Go to **Actions → Allocator Master Destroy**
2. Click **Run workflow**
3. Select environment
4. Confirm destruction

### Via Terraform CLI

```bash
cd lablink-allocator

terraform destroy \
  -var="resource_suffix=dev" \
  -var="allocator_image_tag=dummy"  # Still required

# Type 'yes' to confirm
```

**Warning**: This destroys:
- EC2 instance
- Security group
- SSH key pair
- All associated resources

**Not destroyed**:
- S3 bucket (Terraform state)
- Elastic IPs (must be released manually)
- Any client VMs created by the allocator

## Troubleshooting Deployments

### Terraform Init Fails

**Error**: `Backend configuration changed`

**Solution**:
```bash
terraform init -reconfigure
```

### Apply Fails: Resource Already Exists

**Error**: `Error creating security group: ... already exists`

**Solution**: Import existing resource or destroy manually:
```bash
terraform import aws_security_group.lablink sg-xxxxx
```

### SSH Key Not Working

**Error**: `Permission denied (publickey)`

**Check**:
```bash
# Verify key permissions
ls -l ~/lablink-key.pem
# Should show: -rw------- (600)

# Fix permissions
chmod 600 ~/lablink-key.pem
```

### Instance Not Accessible

**Check**:
1. Security group allows port 80 from your IP
2. Instance has public IP
3. Instance is running (`aws ec2 describe-instances`)

### Terraform State Locked

**Error**: `Error acquiring the state lock`

**Solution**:
```bash
# If no other Terraform process is running:
terraform force-unlock <lock-id>
```

## Best Practices

1. **Use version control**: Always commit Terraform configs before applying
2. **Review plans**: Always run `terraform plan` before `apply`
3. **Pin versions**: Use specific image tags in production
4. **Separate environments**: Never share state between dev/test/prod
5. **Backup state**: Enable S3 versioning for Terraform state
6. **Monitor costs**: Set up AWS billing alerts
7. **Document changes**: Use descriptive commit messages

## Next Steps

- **[Workflows](workflows.md)**: Understand the CI/CD pipeline
- **[SSH Access](ssh-access.md)**: Connect to your deployed instances
- **[Database Management](database.md)**: Manage the allocator database
- **[Troubleshooting](troubleshooting.md)**: Fix common deployment issues

## Cost Management

See [Cost Estimation](cost-estimation.md) for expected AWS costs and how to monitor spending.