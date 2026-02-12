# Quickstart

Get LabLink deployed to AWS using the template repository and automation scripts.

## Prerequisites

Before starting, ensure you have completed:

- [x] [Prerequisites](prerequisites.md): AWS CLI, Terraform, Docker, Git installed
- [x] [AWS Setup](aws-setup.md): IAM permissions, OIDC provider, and GitHub Actions role configured

## Step 1: Create Your Repository

Click the **"Use this template"** button on the [lablink-template repository](https://github.com/talmolab/lablink-template) to create your own deployment repository.

Then clone your new repository:

```bash
git clone https://github.com/YOUR_ORG/YOUR_REPO.git
cd YOUR_REPO
```

## Step 2: Configure Settings

Copy the example config and edit the minimal required settings:

```bash
cd lablink-infrastructure
```

Edit `config/config.yaml` with your deployment settings:

```yaml
# Minimal configuration for quick start
app:
  region: "us-west-2"  # Must match your AWS_REGION secret
  admin_password: "PLACEHOLDER_ADMIN_PASSWORD"  # Replaced by GitHub secret

db:
  password: "PLACEHOLDER_DB_PASSWORD"  # Replaced by GitHub secret

dns:
  enabled: false  # Start without DNS, use IP address

ssl:
  provider: "none"  # Start without HTTPS

machine:
  ami_id: "ami-0601752c11b394251"  # LabLink custom AMI (us-west-2)
  machine_type: "t3.medium"

allocator_instance:
  ami_id: "ami-0bd08c9d4aa9f0bc6"  # LabLink custom AMI (us-west-2)
```

!!! note "Other Regions"
    If deploying outside `us-west-2`, you'll need to find or copy AMI IDs for your region. See [AWS Setup - Find AMI IDs](aws-setup.md#step-5-find-ami-ids-for-your-region).

## Step 3: Run AWS Setup Script

The template includes a script that creates the required AWS resources (S3 bucket for Terraform state, DynamoDB lock table, and optionally Route 53 hosted zone):

```bash
scripts/setup-aws-infrastructure.sh
```

This script will:

- Create an S3 bucket for Terraform state storage
- Enable versioning and encryption on the bucket
- Create a DynamoDB table for state locking
- Optionally create a Route 53 hosted zone for DNS

!!! tip "Manual Setup"
    If you prefer to create these resources manually, see [AWS Setup - Step 2](aws-setup.md#step-2-s3-bucket-for-terraform-state) for detailed instructions.

## Step 4: Set Up GitHub Actions Secrets

In your GitHub repository, go to **Settings** → **Secrets and variables** → **Actions** and add these four secrets:

| Secret | Description |
|--------|-------------|
| `AWS_ROLE_ARN` | ARN of the IAM role for GitHub Actions (e.g., `arn:aws:iam::123456789:role/GitHubActionsLabLinkRole`) |
| `AWS_REGION` | Your AWS region (e.g., `us-west-2`) |
| `ADMIN_PASSWORD` | Secure password for the admin web interface |
| `DB_PASSWORD` | Secure password for the PostgreSQL database |

!!! warning "Use Strong Passwords"
    Generate strong, unique passwords for `ADMIN_PASSWORD` and `DB_PASSWORD` using a password manager. These are injected during deployment and replace the placeholder values in `config.yaml`.

## Step 5: Deploy to Test

Push to the `test` branch to trigger a deployment:

```bash
git checkout -b test
git push -u origin test
```

Monitor the deployment:

1. Go to the **Actions** tab in your GitHub repository
2. Watch the **Terraform Deploy** workflow
3. Wait for the workflow to complete (~5-10 minutes)

The workflow will:

- Authenticate to AWS via OIDC
- Initialize Terraform with the S3 backend
- Deploy the allocator EC2 instance, security groups, and SSH key pair

## Step 6: Verify

Once the deployment completes:

### Access the Web UI

1. Find the allocator's public IP from the Terraform output in the GitHub Actions logs
2. Navigate to `http://<ec2_public_ip>` in your browser
3. Log in with username `admin` and the `ADMIN_PASSWORD` you set

### Create Test VMs

1. Go to `http://<ec2_public_ip>/admin`
2. Click **"Create VMs"**
3. Enter number of VMs (try 1-2 for testing)
4. Click **"Launch VMs"** and wait ~5 minutes

### SSH Check

```bash
# Download the SSH key from Terraform output (via GitHub Actions artifacts or manually)
ssh -i ~/lablink-key.pem ubuntu@<ec2_public_ip>

# Verify allocator is running
sudo docker ps

# Check VMs registered in database
sudo docker exec $(sudo docker ps -q) psql -U lablink -d lablink_db -c "SELECT hostname FROM vms;"
```

## Step 7: Cleanup

When you're done testing, destroy the infrastructure:

=== "Via GitHub Actions"

    Delete the `test` branch to trigger the destroy workflow, or manually run the **Terraform Destroy** workflow from the Actions tab.

=== "Via Terraform"

    ```bash
    cd lablink-infrastructure
    scripts/init-terraform.sh test
    terraform destroy -var="resource_suffix=test"
    ```

=== "Cleanup Orphaned Resources"

    If resources were left behind (e.g., from a failed destroy), use the cleanup script:

    ```bash
    scripts/cleanup-orphaned-resources.sh test
    ```

!!! warning "AWS Costs"
    EC2 instances incur charges while running. Always destroy test resources when not in use. See [Cost Estimation](cost-estimation.md) for details.

## Next Steps

- **[Configuration](configuration.md)**: Customize instance types, machine images, and deployment settings
- **[Adapting for Your Software](adapting.md)**: Install your own tutorial software on client VMs
- **[Deployment](deployment.md)**: Production deployment with CI/CD workflows
- **[Security](security.md)**: Review security best practices before going to production
