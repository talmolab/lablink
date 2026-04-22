# Quickstart: Template repo

Deploy LabLink to AWS by creating a repository from [lablink-template](https://github.com/talmolab/lablink-template) and pushing commits to `main`. GitHub Actions runs Terraform against shared S3-backed state. Best for workshops, shared environments, and production.

!!! tip "Prefer a local flow?"
    The [CLI quickstart](cli/first-deployment.md) deploys the same infrastructure from your own machine with `lablink configure && lablink deploy`. Both paths are equivalent — pick whichever fits your setup.

## Prerequisites

Before starting, ensure you have completed:

- [x] [Prerequisites](prerequisites.md): AWS Account, AWS CLI, GitHub CLI (`gh`), and Git installed

## Step 1: Create Your Repository

<div class="video-container">
  <video controls width="100%">
    <source src="../assets/videos/step1-create-repo.mp4" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

Click the **"Use this template"** button on the [lablink-template repository](https://github.com/talmolab/lablink-template) to create your own deployment repository.

Then clone your new repository:

```bash
git clone https://github.com/YOUR_ORG/YOUR_REPO.git
cd YOUR_REPO
```

## Step 2: Run Setup

<div class="video-container">
  <video controls width="100%">
    <source src="../assets/videos/step2-run-setup.mp4" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

Run the setup script to create all required AWS resources and configure GitHub secrets:

```bash
./scripts/setup.sh
```

The script will prompt you for:

- AWS region (e.g., `us-west-2`)
- S3 bucket name for Terraform state
- GitHub repository (e.g., `YOUR_ORG/YOUR_REPO`)
- Optional DNS settings (Route 53)

It automatically:

- Creates an OIDC identity provider for GitHub Actions
- Creates an IAM role with required permissions
- Creates an S3 bucket for Terraform state (with versioning and encryption)
- Creates a DynamoDB table for state locking
- Optionally creates a Route 53 hosted zone
- Sets four GitHub repository secrets: `AWS_ROLE_ARN`, `AWS_REGION`, `ADMIN_PASSWORD`, `DB_PASSWORD`
- Generates secure passwords for admin and database access

!!! tip "Manual Setup"
    If you prefer to create AWS resources individually, see the [AWS Setup (Manual)](aws-setup.md) guide.

## Step 3: Configure

After setup completes, the script automatically runs `./scripts/configure.sh` to generate your deployment configuration.

The configure script prompts for:

- Instance type and AMI settings
- DNS and SSL configuration
- Monitoring options

It generates `lablink-infrastructure/config/config.yaml` with your settings.

!!! note "Re-running Configuration"
    You can re-run the configuration script at any time to update settings:
    ```bash
    ./scripts/configure.sh
    ```

## Step 4: Commit and Deploy

<div class="video-container">
  <video controls width="100%">
    <source src="../assets/videos/step4-commit-deploy.mp4" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

Commit your configuration and push to the `main` branch:

```bash
git add lablink-infrastructure/config/config.yaml
git commit -m "Add deployment configuration"
git push
```

Monitor the deployment:

1. Go to the **Actions** tab in your GitHub repository
2. Run the **Terraform Deploy** workflow manually
4. Wait for the workflow to complete (~2-5 minutes)

<div class="video-container">
  <video controls width="100%">
    <source src="../assets/videos/step4-deploy.mp4" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

The workflow will:

- Authenticate to AWS via OIDC
- Initialize Terraform with the S3 backend
- Deploy the allocator EC2 instance, security groups, and SSH key pair

## Step 5: Verify

<div class="video-container">
  <video controls width="100%">
    <source src="../assets/videos/step5-verify.mp4" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

Once the deployment completes:

### Access the Web UI

1. Find the allocator's public IP from the Terraform output in the GitHub Actions logs
2. Navigate to `http://<ec2_public_ip>` in your browser
3. Log in with username `admin` and the `ADMIN_PASSWORD` that was auto-generated during setup

### Create Test VMs

1. Go to `http://<ec2_public_ip>/admin`
2. Click **"Create VMs"**
3. Enter number of VMs (try 1-2 for testing)
4. Click **"Launch VMs"** and wait ~5 minutes

### Verify Deployment Script (Optional)

The template includes a verification script:

```bash
./scripts/verify-deployment.sh
```

### SSH Check

```bash
# Download the SSH key from Terraform output (via GitHub Actions artifacts or manually)
ssh -i ~/lablink-key.pem ubuntu@<ec2_public_ip>

# Verify allocator is running
sudo docker ps

# Check VMs registered in database
sudo docker exec $(sudo docker ps -q) psql -U lablink -d lablink_db -c "SELECT hostname FROM vms;"
```

## Step 6: Cleanup

<div class="video-container">
  <video controls width="100%">
    <source src="../assets/videos/step6-cleanup.mp4" type="video/mp4">
    Your browser does not support the video tag.
  </video>
</div>

When you're done testing, destroy the infrastructure:

=== "Via GitHub Actions"

    Manually run the **Terraform Destroy** workflow from the Actions tab.

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
