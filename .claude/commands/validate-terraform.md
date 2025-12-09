# Validate Terraform Configurations

Validate Terraform configurations for client VM provisioning.

## Quick Validation (Local Development)

For local development without AWS credentials, you need to remove the S3 backend configuration:

```bash
# Navigate to Terraform directory
cd packages/allocator/src/lablink_allocator/terraform

# Remove backend configuration for local testing (if backend.tf exists)
# This is required because the S3 backend requires AWS credentials
mv backend.tf backend.tf.bak 2>/dev/null || true

# Initialize Terraform (local backend)
terraform init

# Validate configuration
terraform validate

# Restore backend.tf when done
mv backend.tf.bak backend.tf 2>/dev/null || true
```

**Note**: The S3 backend configuration in `backend.tf` requires AWS credentials. For local validation, temporarily remove or rename this file.

## Full Validation Process

### 1. Format Check

```bash
cd packages/allocator/src/lablink_allocator/terraform

# Check formatting
terraform fmt -check

# Auto-format (if needed)
terraform fmt
```

### 2. Initialize Terraform

```bash
# Initialize (downloads providers)
terraform init

# Or force re-initialization
terraform init -upgrade
```

### 3. Validate Syntax

```bash
# Validate Terraform files
terraform validate
```

Expected output:
```
Success! The configuration is valid.
```

### 4. Plan (Dry Run)

```bash
# Create execution plan (requires AWS credentials)
terraform plan \
  -var="instance_count=1" \
  -var="instance_type=t3.micro" \
  -var="ami_id=ami-0c55b159cbfafe1f0" \
  -var="docker_image=lablink-client:latest" \
  -var="docker_repo=ghcr.io/talmolab" \
  -var="allocator_host=allocator.example.com" \
  -var="allocator_port=5000" \
  -var="key_name=lablink-key" \
  -var="region=us-east-1" \
  -var="security_group_id=sg-12345" \
  -var="subnet_id=subnet-12345"
```

**Note**: Plan requires valid AWS credentials but won't create resources.

## CI Testing Pattern

The CI workflow validates Terraform by removing the S3 backend dependency:

```bash
# 1. Remove backend configuration (S3 dependency)
# On Linux/CI:
sed -i '/backend "s3"/,/}/d' backend.tf
# On macOS:
sed -i '' '/backend "s3"/,/}/d' backend.tf
# On Windows (PowerShell):
(Get-Content backend.tf) -notmatch 'backend "s3"' | Set-Content backend.tf

# 2. Initialize with local backend
terraform init

# 3. Validate syntax
terraform validate

# 4. Plan with fixture data (requires AWS credentials for provider)
terraform plan \
  -var="instance_count=2" \
  -var="instance_type=t3.small" \
  # ... other required variables
```

This validates syntax and logic without creating resources.

**Why remove the backend?** The S3 backend configuration requires AWS credentials to even initialize Terraform. By removing it, we can validate syntax with a local backend.

## Terraform Files

```
packages/allocator/src/lablink_allocator/terraform/
├── main.tf         # Client VM resources
├── variables.tf    # Input variables
├── outputs.tf      # Output values
└── backend.tf      # S3 backend config (optional)
```

## Common Validations

### Check Required Variables

```bash
# List all variables
grep "^variable" variables.tf

# Ensure all variables have defaults or are provided
terraform validate
```

### Verify Resource Definitions

```bash
# Check EC2 instance configuration
grep -A 20 "resource \"aws_instance\"" main.tf

# Check user_data script
grep -A 50 "user_data" main.tf
```

### Test Variable Substitution

```bash
# Plan with different variable values
terraform plan \
  -var="instance_count=3" \
  -var="instance_type=t3.medium" \
  # ... other variables
```

## Linting (Optional)

### tflint

```bash
# Install tflint
# macOS: brew install tflint
# Windows: choco install tflint
# Linux: curl -s https://raw.githubusercontent.com/terraform-linters/tflint/master/install_linux.sh | bash

# Run tflint
cd packages/allocator/src/lablink_allocator/terraform
tflint
```

### terraform-docs

```bash
# Install terraform-docs
# macOS: brew install terraform-docs
# Windows: choco install terraform-docs
# Linux: See https://terraform-docs.io/user-guide/installation/

# Generate documentation
terraform-docs markdown . > TERRAFORM.md
```

## Troubleshooting

### Terraform Not Initialized
**Symptom**: `Error: Terraform has not been initialized`

**Solution**:
```bash
terraform init
```

### Invalid Provider Version
**Symptom**: `Error: Unsupported Terraform Core version`

**Solution**:
```bash
# Check Terraform version
terraform version

# Update if needed (requires Terraform 1.0+)
# Install from: https://www.terraform.io/downloads
```

### Backend Configuration Error
**Symptom**: `Error: Backend initialization required` or `Error: Failed to get existing workspaces`

**Solution for local testing**:
```bash
# Option 1: Temporarily remove backend.tf
mv backend.tf backend.tf.bak
terraform init
terraform validate
mv backend.tf.bak backend.tf

# Option 2: Use -backend=false (syntax check only)
terraform init -backend=false
terraform validate
```

**Solution with AWS credentials**:
```bash
terraform init \
  -backend-config="bucket=lablink-terraform-state" \
  -backend-config="key=terraform.tfstate" \
  -backend-config="region=us-east-1"
```

### Missing Required Variables
**Symptom**: `Error: No value for required variable`

**Solution**:
```bash
# Provide all required variables
terraform plan \
  -var="instance_count=1" \
  -var="instance_type=t3.micro" \
  # ... all other required variables
```

### AWS Credentials Not Found
**Symptom**: `Error: No valid credential sources found`

**Note**: This is expected for syntax validation. You don't need AWS credentials for `terraform validate`.

For full plan validation:
```bash
# Configure AWS credentials
aws configure

# Or use environment variables
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1
```

## CI Integration

Terraform validation runs in `.github/workflows/ci.yml`:

```yaml
- name: Terraform Validate
  run: |
    cd packages/allocator/src/lablink_allocator/terraform
    terraform init
    terraform validate
```

Also includes plan tests with fixture data.

## Best Practices

### Before Committing

```bash
# 1. Format Terraform files
terraform fmt

# 2. Validate syntax (may need to remove backend.tf first)
terraform init -backend=false
terraform validate

# 3. Test plan (if you have AWS credentials)
terraform plan -out=tfplan

# 4. Run allocator unit tests (excludes Terraform tests locally)
cd packages/allocator
uv run pytest tests --ignore=tests/terraform
```

**Note**: Terraform integration tests (`tests/terraform/`) require AWS OIDC credentials and are run in CI only.

### When Modifying Terraform

1. Update resource definitions in `main.tf`
2. Add/update variables in `variables.tf`
3. Update outputs in `outputs.tf`
4. Run `terraform fmt`
5. Run `terraform validate`
6. Update tests in `tests/terraform/`
7. Run pytest to verify tests pass

## Related Commands

- `/test-allocator` - Run allocator tests (includes Terraform tests)
- `/lint` - Check Python code quality