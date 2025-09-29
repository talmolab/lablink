# Workflows

This guide explains LabLink's CI/CD workflows, how they work, and how to customize them.

## Overview

LabLink uses GitHub Actions for continuous integration and deployment. The workflows automate:

- Docker image building and publishing
- Infrastructure deployment via Terraform
- Testing and validation
- Environment management

## Workflow Files

All workflows are located in `.github/workflows/`:

| Workflow File | Purpose | Trigger |
|---------------|---------|---------|
| [`lablink-images.yml`](#image-building-workflow) | Build and push Docker images | Push to branches, PRs |
| [`lablink-allocator-terraform.yml`](#terraform-deployment-workflow) | Deploy infrastructure | Push to `test`, manual dispatch |
| [`lablink-allocator-destroy.yml`](#destroy-workflow) | Destroy environment | Manual only |
| [`client-vm-infrastructure-test.yml`](#infrastructure-testing-workflow) | Test client VM creation | Manual/scheduled |
| [`ci.yml`](#continuous-integration-workflow) | Run unit tests | PRs, pushes |

## Image Building Workflow

**File**: `.github/workflows/lablink-images.yml`

### Purpose

Builds and publishes Docker images to GitHub Container Registry (ghcr.io).

### Triggers

- **Push to `main`**: Creates images tagged `:latest`
- **Push to other branches**: Creates images tagged `:<branch>-test`
- **Pull requests**: Builds but doesn't push

### What It Does

1. **Check for Changes**
   - Detects changes in allocator or client directories
   - Skips unnecessary builds

2. **Build Allocator Image**
   - Builds from `lablink-allocator/Dockerfile`
   - Tags: `ghcr.io/talmolab/lablink-allocator-image:<tag>`

3. **Build Client Image**
   - Builds from `lablink-client-base/lablink-client-base-image/Dockerfile`
   - Tags: `ghcr.io/talmolab/lablink-client-base-image:<tag>`

4. **Push to Registry**
   - Authenticates to ghcr.io
   - Pushes images with appropriate tags

### Image Tagging Strategy

| Branch/Event | Tag Format | Example |
|--------------|------------|---------|
| `main` branch | `linux-amd64-latest` | `ghcr.io/.../image:linux-amd64-latest` |
| Other branches | `linux-amd64-<branch>-test` | `ghcr.io/.../image:linux-amd64-dev-test` |
| Pull requests | Build only, no push | N/A |
| Releases | `v<version>` | `ghcr.io/.../image:v1.0.0` |

### Example Workflow Run

```
1. Developer pushes to branch `feature/new-api`
2. Workflow triggered
3. Checks for changes in allocator/client dirs
4. Builds images
5. Tags as `linux-amd64-feature-new-api-test`
6. Pushes to ghcr.io
7. Images available for deployment
```

### Customization

To modify image building:

```yaml
# .github/workflows/lablink-images.yml

# Build for different platforms
- name: Build and push
  uses: docker/build-push-action@v5
  with:
    platforms: linux/amd64,linux/arm64  # Add ARM support
    push: ${{ github.event_name != 'pull_request' }}
    tags: ${{ steps.meta.outputs.tags }}
```

## Terraform Deployment Workflow

**File**: `.github/workflows/lablink-allocator-terraform.yml`

### Purpose

Deploys LabLink infrastructure to AWS using Terraform.

### Triggers

- **Push to `test` branch**: Automatic test deployment
- **Workflow dispatch**: Manual deployment (dev/test/prod)
- **Repository dispatch**: Programmatic deployment (for prod)

### Input Parameters (Manual Dispatch)

| Parameter | Description | Required | Default |
|-----------|-------------|----------|---------|
| `environment` | Environment to deploy (`dev`, `test`, `prod`) | Yes | `dev` |
| `image_tag` | Docker image tag (required for prod) | For prod only | N/A |

### Workflow Steps

#### 1. Environment Determination

```
Push to 'test' branch → env=test
Manual dispatch → env=<user input>
Repository dispatch → env=<payload>
```

#### 2. AWS Authentication

Uses OpenID Connect (OIDC) to assume IAM role:
```yaml
- name: Configure AWS credentials via OIDC
  uses: aws-actions/configure-aws-credentials@v3
  with:
    role-to-assume: arn:aws:iam::711387140753:role/github_lablink_repository-AE68499B37C7
    aws-region: us-west-2
```

**No AWS credentials stored in GitHub!**

#### 3. Terraform Initialization

```bash
# Dev (local state)
terraform init

# Test/Prod (remote state)
terraform init -backend-config=backend-<env>.hcl
```

#### 4. Validation

```bash
terraform fmt -check  # Check formatting
terraform validate    # Validate syntax
```

#### 5. Planning

```bash
terraform plan \
  -var="resource_suffix=<env>" \
  -var="allocator_image_tag=<tag>"
```

#### 6. Application

```bash
terraform apply -auto-approve \
  -var="resource_suffix=<env>" \
  -var="allocator_image_tag=<tag>"
```

#### 7. Artifact Handling

- Extracts SSH private key from Terraform output
- Saves as artifact (expires in 1 day)
- Provides download link in workflow summary

#### 8. Failure Handling

If `terraform apply` fails:
```bash
terraform destroy -auto-approve
```

Automatically cleans up partial deployments.

### Example Workflow Run

**Scenario**: Deploy to production

```
1. Navigate to Actions → Terraform Deploy → Run workflow
2. Select:
   - Environment: prod
   - Image tag: v1.0.0
3. Workflow starts:
   - Authenticates to AWS via OIDC
   - Initializes Terraform with backend-prod.hcl
   - Plans infrastructure
   - Applies changes
   - Saves SSH key to artifacts
4. Deployment complete
5. Outputs displayed in workflow summary:
   - Allocator FQDN: lablink-prod.example.com
   - EC2 Public IP: 54.xxx.xxx.xxx
   - EC2 Key Name: lablink-prod-key
```

### Customization

To add deployment notifications:

```yaml
# Add at end of workflow
- name: Notify Slack
  if: success()
  uses: slackapi/slack-github-action@v1
  with:
    webhook-url: ${{ secrets.SLACK_WEBHOOK }}
    payload: |
      {
        "text": "LabLink deployed to ${{ steps.setenv.outputs.env }}!"
      }
```

## Destroy Workflow

**File**: `.github/workflows/lablink-allocator-destroy.yml`

### Purpose

Safely destroy LabLink infrastructure for an environment.

### Triggers

- **Manual dispatch only**: Requires explicit user action

### Input Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `environment` | Environment to destroy (`dev`, `test`, `prod`) | Yes |

### Safety Features

- Manual trigger only (no automatic destruction)
- Requires environment selection
- Shows plan before destroying
- Logs all destroyed resources

### Workflow Steps

1. Authenticate to AWS via OIDC
2. Initialize Terraform with correct backend
3. Plan destruction
4. Execute `terraform destroy -auto-approve`
5. Output destroyed resources

### Example Usage

```
1. Navigate to Actions → Allocator Master Destroy
2. Click "Run workflow"
3. Select environment: dev
4. Confirm
5. Workflow destroys:
   - EC2 instance
   - Security group
   - SSH key pair
6. Terraform state updated
```

!!! warning "Destructive Operation"
    This action is **irreversible**. Ensure you have backups of any data before destroying.

## Infrastructure Testing Workflow

**File**: `.github/workflows/client-vm-infrastructure-test.yml`

### Purpose

End-to-end test of client VM creation and management.

### Triggers

- **Manual dispatch**: On-demand testing
- **Scheduled**: Nightly/weekly regression tests (optional)

### What It Tests

1. Allocator deployment
2. Client VM spawning
3. VM registration with allocator
4. Health check reporting
5. VM destruction

### Test Workflow

```
1. Deploy test allocator
2. Request client VM via API
3. Wait for VM to be created and register
4. Verify VM appears in allocator database
5. Check VM health status
6. Destroy client VM
7. Destroy allocator
8. Verify all resources cleaned up
```

## Continuous Integration Workflow

**File**: `.github/workflows/ci.yml`

### Purpose

Run unit tests and code quality checks on pull requests.

### Triggers

- Pull requests to `main`
- Pushes to `main` or development branches

### Steps

1. **Setup Python Environment**
   ```yaml
   - uses: actions/setup-python@v4
     with:
       python-version: '3.11'
   ```

2. **Install Dependencies**
   ```bash
   pip install pytest pytest-cov ruff
   ```

3. **Run Linting**
   ```bash
   ruff check .
   ```

4. **Run Tests**
   ```bash
   pytest --cov=lablink_allocator_service
   pytest --cov=lablink_client_service
   ```

5. **Upload Coverage**
   - Generates coverage report
   - Uploads to coverage service (optional)

### Adding More Tests

Edit `ci.yml` to add test steps:

```yaml
- name: Run integration tests
  run: |
    pytest tests/integration/

- name: Security scan
  run: |
    pip install bandit
    bandit -r lablink_allocator_service/
```

## Workflow Environment Variables

Common environment variables used across workflows:

| Variable | Description | Source |
|----------|-------------|--------|
| `GITHUB_TOKEN` | GitHub API token | Automatic |
| `AWS_REGION` | AWS region | Hardcoded (us-west-2) |
| `GITHUB_REPOSITORY` | Repo name | Automatic |
| `GITHUB_REF_NAME` | Branch/tag name | Automatic |

## Secrets Management

### Required Secrets

| Secret | Purpose | Where Used |
|--------|---------|------------|
| None! | OIDC handles AWS auth | All AWS workflows |

### Optional Secrets

| Secret | Purpose | How to Set |
|--------|---------|------------|
| `ADMIN_PASSWORD` | Override admin password | Settings → Secrets |
| `DB_PASSWORD` | Override DB password | Settings → Secrets |
| `SLACK_WEBHOOK` | Notifications | Settings → Secrets |

### Adding Secrets

```
1. Go to repository Settings
2. Navigate to Secrets and variables → Actions
3. Click "New repository secret"
4. Name: ADMIN_PASSWORD
5. Value: your-secure-password
6. Click "Add secret"
```

Access in workflows:
```yaml
- name: Use secret
  env:
    ADMIN_PASSWORD: ${{ secrets.ADMIN_PASSWORD }}
  run: |
    echo "Password is set"
```

## Workflow Monitoring

### View Workflow Runs

1. Navigate to **Actions** tab in GitHub
2. Select workflow from left sidebar
3. View recent runs

### Workflow Status

- ✅ Green checkmark: Success
- ❌ Red X: Failure
- 🟡 Yellow dot: In progress
- ⚪ Gray circle: Queued

### Debugging Failed Workflows

1. Click on failed workflow run
2. Click on failed job
3. Expand failed step
4. Read error logs
5. Fix issue and re-run

### Re-running Workflows

From workflow run page:
- **Re-run all jobs**: Retry entire workflow
- **Re-run failed jobs**: Only retry failures

## Creating Custom Workflows

### Example: Backup Workflow

Create `.github/workflows/backup.yml`:

```yaml
name: Backup Database

on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM
  workflow_dispatch:

jobs:
  backup:
    runs-on: ubuntu-latest
    steps:
      - name: Configure AWS
        uses: aws-actions/configure-aws-credentials@v3
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: us-west-2

      - name: Backup Database
        run: |
          # SSH into allocator
          # Run pg_dump
          # Upload to S3
          echo "Backup complete"
```

### Example: Notification Workflow

```yaml
name: Deployment Notifications

on:
  workflow_run:
    workflows: ["Terraform Deploy"]
    types: [completed]

jobs:
  notify:
    runs-on: ubuntu-latest
    steps:
      - name: Send Email
        uses: dawidd6/action-send-mail@v3
        with:
          server_address: smtp.gmail.com
          server_port: 465
          username: ${{ secrets.EMAIL_USERNAME }}
          password: ${{ secrets.EMAIL_PASSWORD }}
          subject: "LabLink Deployment: ${{ github.event.workflow_run.conclusion }}"
          body: "Deployment finished with status: ${{ github.event.workflow_run.conclusion }}"
          to: admin@example.com
```

## Best Practices

1. **Pin action versions**: Use `@v3` not `@latest`
2. **Minimize secrets**: Use OIDC when possible
3. **Cache dependencies**: Speed up workflows
4. **Fail fast**: Stop on first error
5. **Use matrix builds**: Test multiple versions
6. **Set timeouts**: Prevent runaway workflows
7. **Add status badges**: Show workflow status in README

### Status Badge Example

Add to `README.md`:
```markdown
![CI](https://github.com/talmolab/lablink/actions/workflows/ci.yml/badge.svg)
![Deploy](https://github.com/talmolab/lablink/actions/workflows/lablink-allocator-terraform.yml/badge.svg)
```

## Troubleshooting Workflows

### Workflow Won't Trigger

**Check**:
- Workflow file syntax (use YAML validator)
- Trigger conditions match your action
- Workflows enabled in repository settings

### AWS Authentication Fails

**Check**:
- IAM role ARN is correct
- Trust policy includes GitHub OIDC provider
- Role has necessary permissions

### Terraform Failures

**Check**:
- Terraform syntax (`terraform validate`)
- AWS resource limits
- Terraform state lock status

### Image Push Fails

**Check**:
- GHCR authentication (should be automatic)
- Image size limits
- Registry permissions

## Next Steps

- **[Deployment](deployment.md)**: Deploy using these workflows
- **[Security](security.md)**: Understand OIDC and secrets
- **[AWS Setup](aws-setup.md)**: Configure AWS for workflows
- **[Troubleshooting](troubleshooting.md)**: Fix workflow issues