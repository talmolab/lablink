# Configuration

LabLink uses structured configuration files to customize behavior. This guide covers all configuration options and how to modify them.

!!! info "Infrastructure Repository"
    Configuration files are located in the [lablink-template](https://github.com/talmolab/lablink-template) repository under `lablink-infrastructure/config/config.yaml`. Clone the template repository to deploy LabLink infrastructure.

## First Steps: Change Default Passwords

!!! danger "Critical Security Step"
    **Before deploying LabLink or creating any VMs, you MUST configure secure passwords!**

Configuration files use placeholder values that must be replaced with secure passwords:
- **Admin password placeholder**: `PLACEHOLDER_ADMIN_PASSWORD`
- **Database password placeholder**: `PLACEHOLDER_DB_PASSWORD`

### How to Configure Passwords

**Method 1: GitHub Secrets (Recommended for CI/CD)**

For GitHub Actions deployments, add secrets to your repository:

1. Go to repository **Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. Add `ADMIN_PASSWORD` with your secure admin password
4. Add `DB_PASSWORD` with your secure database password

The deployment workflow automatically replaces placeholders with these secret values before Terraform runs, preventing passwords from appearing in logs.

**Method 2: Manual Configuration**

For local deployments, edit the configuration file:

```bash
# Edit allocator configuration
vi lablink-infrastructure/config/config.yaml
```

Update these values:
```yaml
db:
  password: "YOUR_SECURE_DB_PASSWORD_HERE"  # Replace PLACEHOLDER_DB_PASSWORD

app:
  admin_password: "YOUR_SECURE_PASSWORD_HERE"  # Replace PLACEHOLDER_ADMIN_PASSWORD
```

**Method 3: Environment Variables**

```bash
export ADMIN_PASSWORD="your_secure_password"
export DB_PASSWORD="your_secure_db_password"
```

**Password requirements**:
- Minimum 12 characters
- Mix of uppercase, lowercase, numbers, symbols
- Not a dictionary word
- Use a password manager to generate and store

See [Security → Change Default Passwords](security.md#change-default-passwords) for detailed security guidance.

## Configuration System

LabLink uses [Hydra](https://hydra.cc/) for configuration management, which provides:

- **Structured configs**: Type-safe dataclass-based configuration
- **Hierarchical composition**: Override specific values
- **Environment variables**: Override via `ENV_VAR` syntax
- **Command-line overrides**: Pass config values as arguments

## Configuration Files

### Allocator Configuration

**Location**: `lablink-infrastructure/config/config.yaml`

```yaml
db:
  dbname: "lablink_db"
  user: "lablink"
  password: "PLACEHOLDER_DB_PASSWORD"  # Injected from GitHub secret at deploy time
  host: "localhost"
  port: 5432
  table_name: "vms"
  message_channel: "vm_updates"

machine:
  machine_type: "g4dn.xlarge"
  image: "ghcr.io/talmolab/lablink-client-base-image:linux-amd64-test"
  ami_id: "ami-0601752c11b394251"
  repository: "https://github.com/talmolab/sleap-tutorial-data.git"
  software: "sleap"
  extension: "slp"

app:
  admin_user: "admin"
  admin_password: "PLACEHOLDER_ADMIN_PASSWORD"  # Injected from GitHub secret at deploy time
  region: "us-west-2"

dns:
  enabled: true
  terraform_managed: false
  domain: "dev.lablink.sleap.ai"
  zone_id: ""

eip:
  strategy: "dynamic"
  tag_name: "lablink-eip"

ssl:
  provider: "letsencrypt"
  email: "admin@sleap.ai"
  certificate_arn: ""

allocator:
  image_tag: "linux-amd64-latest-test"

bucket_name: "tf-state-lablink-allocator-bucket"

startup_script:
  enabled: false
  path: ""
  on_error: "continue"

monitoring:
  enabled: false
  email: ""
  thresholds:
    max_instances_per_5min: 10
    max_terminations_per_5min: 20
    max_unauthorized_calls_per_15min: 5
  budget:
    enabled: false
    monthly_budget_usd: 500
  cloudtrail:
    retention_days: 90
```

### Client Configuration

**Location**: `packages/client/src/lablink_client/conf/config.yaml`

```yaml
allocator:
  host: "localhost"
  port: 80

client:
  software: "sleap"
```

## Configuration Reference

### Database Options (`db`)

Configuration for the PostgreSQL database.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `dbname` | string | `lablink_db` | Database name |
| `user` | string | `lablink` | Database username |
| `password` | string | `lablink` | Database password (override with `PLACEHOLDER_DB_PASSWORD` or GitHub secret) |
| `host` | string | `localhost` | Database host |
| `port` | int | `5432` | PostgreSQL port |
| `table_name` | string | `vm_table` | VM table name |
| `message_channel` | string | `vm_updates` | PostgreSQL NOTIFY channel |

!!! warning "Production Security"
    Configure `DB_PASSWORD` secret for GitHub Actions deployments, or manually replace the placeholder. See [Security](security.md#database-password).

### Machine Options (`machine`)

Configuration for client VM specifications. **These are the key options for adapting LabLink to your research software.**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `machine_type` | string | `g4dn.xlarge` | AWS EC2 instance type |
| `image` | string | `ghcr.io/talmolab/lablink-client-base-image:latest` | Docker image for client container |
| `ami_id` | string | `ami-00c257e12d6828491` | Amazon Machine Image (Ubuntu 24.04 + Docker + Nvidia) |
| `repository` | string (optional) | `None` | Git repository to clone on VM |
| `software` | string | `sleap` | Software identifier (used by client) |
| `extension` | string | `slp` | File extension associated with the software's data files |

#### Machine Type Options

Common GPU instance types:

| Instance Type | GPU | vCPUs | Memory | GPU Memory | Use Case |
|---------------|-----|-------|--------|------------|----------|
| `g4dn.xlarge` | NVIDIA T4 | 4 | 16 GB | 16 GB | Light workloads, testing |
| `g4dn.2xlarge` | NVIDIA T4 | 8 | 32 GB | 16 GB | Medium workloads |
| `g5.xlarge` | NVIDIA A10G | 4 | 16 GB | 24 GB | Training, inference |
| `g5.2xlarge` | NVIDIA A10G | 8 | 32 GB | 24 GB | Large models |
| `p3.2xlarge` | NVIDIA V100 | 8 | 61 GB | 16 GB | Deep learning training |

See [AWS Instance Types](https://aws.amazon.com/ec2/instance-types/) for complete list.

#### Docker Image

**Default**: `ghcr.io/talmolab/lablink-client-base-image:latest`

The Docker image determines what software runs on your VMs. Options:

1. **Use default SLEAP image** (for SLEAP workflows)
2. **Build custom image** (for your research software) - see [Adapting LabLink](adapting.md)
3. **Use different tag**:
   - `:latest` - latest stable release
   - `:linux-amd64-test` - development version
   - `:v1.0.0` - specific version

#### AMI ID

**Default**: `ami-00c257e12d6828491` (Ubuntu 24.04 + Docker + Nvidia in us-west-2)

The Amazon Machine Image determines the OS and pre-installed software. You may need different AMIs for:

- Different AWS regions (AMI IDs are region-specific)
- Different OS versions
- Custom pre-configured images

**Find AMIs**:
```bash
aws ec2 describe-images \
  --owners 099720109477 \
  --filters "Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*" \
  --query 'Images[*].[ImageId,Name,CreationDate]' \
  --output table
```

#### Repository

**Default**: `None` (no repository cloned)

Git repository to clone onto the client VM. Use this for:

- Custom analysis scripts
- Training data
- Configuration files
- Research code

Set to empty string or omit if no repository needed:
```yaml
repository: ""
```

#### Software Identifier

**Default**: `sleap`

String identifier for the research software. Used by client service for software-specific logic.

#### File Extension

**Default**: `slp`

The file extension associated with the software's data files. Used for identifying relevant data files on the VM.

### Application Options (`app`)

General application settings.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `admin_user` | string | `admin` | Admin username for web UI |
| `admin_password` | string | `admin_password` | Admin password (override with `PLACEHOLDER_ADMIN_PASSWORD` or GitHub secret) |
| `region` | string | `us-west-2` | AWS region for deployments |

!!! danger "Configure Passwords"
    Configure `ADMIN_PASSWORD` secret for GitHub Actions deployments, or manually replace the placeholder. See [Security](security.md#change-default-passwords).

### DNS Options (`dns`)

Controls DNS configuration for allocator hostname.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable DNS-based URLs |
| `terraform_managed` | boolean | `true` | Let Terraform manage Route 53 records |
| `domain` | string | `""` | Full domain name (e.g., `lablink.sleap.ai` or `test.lablink.sleap.ai`) |
| `zone_id` | string | `""` | Route 53 zone ID (optional, skips lookup if provided) |

See [DNS Configuration](dns-configuration.md) for detailed setup instructions.

### EIP Options (`eip`)

Controls Elastic IP allocation strategy.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `strategy` | string | `"dynamic"` | `persistent` = reuse tagged EIP, `dynamic` = create new |
| `tag_name` | string | `"lablink-eip"` | Tag name for persistent EIP lookup |

### SSL/TLS Options (`ssl`)

Controls HTTPS/SSL certificate management.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `provider` | string | `"letsencrypt"` | SSL provider: `letsencrypt`, `cloudflare`, `acm`, or `none` |
| `email` | string | `""` | Email for Let's Encrypt notifications (required when `provider="letsencrypt"`) |
| `certificate_arn` | string | `""` | AWS ACM certificate ARN (required when `provider="acm"`) |

#### SSL Providers

**`letsencrypt`** - Automatic SSL via Caddy + Let's Encrypt

- HTTPS with trusted certificates
- Automatic HTTP → HTTPS redirects
- Requires `dns.enabled: true` and a valid `ssl.email`
- Rate limited (5 duplicate certificates per week per domain)

Configuration example:
```yaml
dns:
  enabled: true
  domain: "lablink.example.com"
ssl:
  provider: "letsencrypt"
  email: "admin@example.com"
```

**`cloudflare`** - CloudFlare proxy handles SSL

- Requires CloudFlare DNS configuration
- Requires `dns.enabled: true` and `dns.terraform_managed: false`

Configuration example:
```yaml
dns:
  enabled: true
  terraform_managed: false
  domain: "lablink.example.com"
ssl:
  provider: "cloudflare"
```

**`acm`** - AWS Certificate Manager

- Uses AWS-managed SSL certificates with an Application Load Balancer
- Requires `dns.enabled: true` and a valid `ssl.certificate_arn`

Configuration example:
```yaml
dns:
  enabled: true
  domain: "lablink.example.com"
ssl:
  provider: "acm"
  certificate_arn: "arn:aws:acm:us-west-2:123456789012:certificate/abc-123"
```

**`none`** - No SSL, HTTP only

- Serves HTTP only on port 80
- No encryption - all traffic is plaintext
- Browser shows "Not Secure" warning
- Useful for testing and development
- May require clearing browser HSTS cache if you previously accessed via HTTPS (see [Troubleshooting](troubleshooting.md#browser-cannot-access-http-staging-mode))

Configuration example:
```yaml
ssl:
  provider: "none"
```

#### SSL Validation Rules

The following rules are enforced during configuration validation:

- SSL `provider` other than `"none"` requires `dns.enabled: true`
- `provider: "letsencrypt"` requires a non-empty `ssl.email`
- `provider: "acm"` requires a non-empty `ssl.certificate_arn`
- `provider: "cloudflare"` requires `dns.terraform_managed: false`

#### Let's Encrypt Rate Limits

When using `provider: "letsencrypt"`:

- 50 certificates per domain per week
- **5 duplicate certificates per week** (same hostnames)
- 300 pending authorizations per account

Use `provider: "none"` for frequent testing to avoid these limits.

#### Browser Access

**With `provider: "none"` (HTTP only):**

1. Type `http://` explicitly in address bar (e.g., `http://test.lablink.sleap.ai`)
2. Clear HSTS cache if you previously accessed via HTTPS
3. Expect "Not Secure" warning (this is normal)

Alternatives:
- Use incognito/private browsing
- Access via IP: `http://<allocator-ip>`
- Use curl: `curl http://test.lablink.sleap.ai`

**With SSL enabled (`letsencrypt`, `cloudflare`, or `acm`):**

Access via `https://your-domain.com` - browser shows secure padlock.

!!! warning "HTTP-only Security"
    `provider: "none"` serves unencrypted HTTP. Never use for production or sensitive data. See [Security](security.md#staging-mode-security).

### Allocator Deployment Options (`allocator`)

Configuration for the allocator service Docker image used during infrastructure deployment. This section is consumed by Terraform, not by the allocator service itself.

| Option      | Type   | Default                | Description                                 |
|-------------|--------|------------------------|---------------------------------------------|
| `image_tag` | string | `"linux-amd64-latest"` | Docker image tag for the allocator service  |

Example tags:

- `linux-amd64-latest` - latest stable release
- `linux-amd64-latest-test` - development version
- `linux-amd64-v1.2.3` - specific version

### Bucket Name

**Option**: `bucket_name`
**Default**: `tf-state-lablink-allocator-bucket`

S3 bucket for Terraform state storage. Must be globally unique.

### Startup Script Options (`startup_script`)

Controls a custom startup script to be run on client VMs after the container starts.

| Option     | Type    | Default    | Description                                      |
|------------|---------|------------|--------------------------------------------------|
| `enabled`  | boolean | `false`    | Enable custom startup script                     |
| `path`     | string  | `""`       | Path to the startup script file                  |
| `on_error` | string  | `continue` | Behavior on script error: `continue` or `fail`   |

**Example:**

```yaml
startup_script:
  enabled: true
  path: "/path/to/your/script.sh"
  on_error: "fail"
```

When `enabled` is `true`, the content of the script specified by `path` will be executed on the client VM.
- If `on_error` is `continue`, any errors in the script will be logged, but the VM will continue to run.
- If `on_error` is `fail`, the VM setup will be aborted if the script returns a non-zero exit code.

### Monitoring Options (`monitoring`)

Configuration for AWS monitoring, alerting, and cost management. When enabled, this deploys CloudWatch alarms, SNS notifications, AWS Budgets, and CloudTrail logging.

| Option    | Type    | Default | Description                           |
|-----------|---------|---------|---------------------------------------|
| `enabled` | boolean | `false` | Enable monitoring infrastructure      |
| `email`   | string  | `""`    | Email address for alert notifications |

#### Thresholds (`monitoring.thresholds`)

Resource usage thresholds that trigger CloudWatch alarms.

| Option                               | Type | Default | Description                                                  |
|--------------------------------------|------|---------|--------------------------------------------------------------|
| `max_instances_per_5min`             | int  | `10`    | Maximum instance launches allowed in a 5-minute window       |
| `max_terminations_per_5min`          | int  | `20`    | Maximum instance terminations allowed in a 5-minute window   |
| `max_unauthorized_calls_per_15min`   | int  | `5`     | Maximum unauthorized API calls allowed in a 15-minute window |

#### Budget (`monitoring.budget`)

AWS Budget configuration for cost management.

| Option               | Type    | Default | Description                 |
|----------------------|---------|---------|-----------------------------|
| `enabled`            | boolean | `false` | Enable budget monitoring    |
| `monthly_budget_usd` | int     | `500`   | Monthly budget limit in USD |

#### CloudTrail (`monitoring.cloudtrail`)

AWS CloudTrail logging configuration for audit trails.

| Option           | Type | Default | Description                              |
|------------------|------|---------|------------------------------------------|
| `retention_days` | int  | `90`    | Number of days to retain CloudTrail logs |

**Example:**

```yaml
monitoring:
  enabled: true
  email: "alerts@example.com"
  thresholds:
    max_instances_per_5min: 10
    max_terminations_per_5min: 20
    max_unauthorized_calls_per_15min: 5
  budget:
    enabled: true
    monthly_budget_usd: 1000
  cloudtrail:
    retention_days: 90
```

## Validating Configuration

After modifying configuration, validate it:

### Schema Validation (Recommended)

Use the built-in validation CLI to check your config against the schema:

```bash
# Validate config file
lablink-validate-config lablink-infrastructure/config/config.yaml

# Output on success:
# ✓ Config validation passed

# Output on error:
# ✗ Config validation failed: Error merging config with schema
#   Unknown keys found: ['unknown_section']
```

The validator checks:

- File exists and is named `config.yaml`
- All keys match the structured config schema
- Required fields are present
- Type mismatches (strings vs integers, etc.)
- Unknown configuration sections
- DNS/SSL dependency rules (e.g., SSL requires DNS enabled)

**Important**: The validator requires the filename to be `config.yaml` to enable Hydra's strict schema matching. Using a different filename will bypass schema validation.

**Usage in CI/CD:**

```bash
# Validate before deployment
lablink-validate-config config/config.yaml && terraform apply || exit 1
```

### Check Syntax

```bash
# YAML syntax check
python -c "import yaml; yaml.safe_load(open('lablink-infrastructure/config/config.yaml'))"
```

### Test Locally

```bash
# Run allocator with custom config
cd packages/allocator
python src/lablink_allocator_service/main.py
```

### Terraform Validation

```bash
cd lablink-infrastructure
terraform validate
terraform plan  # Preview changes
```

## Common Configuration Patterns

### Use Your Own Research Software

```yaml
machine:
  machine_type: "g4dn.2xlarge"
  image: "ghcr.io/yourorg/your-research-image:latest"
  repository: "https://github.com/yourorg/your-research-code.git"
  software: "your-software-name"
  extension: "your-extension"
```

See [Adapting LabLink](adapting.md) for complete guide.

### Multiple GPU Types

Create environment-specific configs:

**`config-cpu.yaml`** (for testing):
```yaml
machine:
  machine_type: "t2.medium"
  ami_id: "ami-0c55b159cbfafe1f0"
```

**`config-gpu.yaml`** (for production):
```yaml
machine:
  machine_type: "g5.xlarge"
  ami_id: "ami-00c257e12d6828491"
```

Use with Hydra:
```bash
python main.py --config-name=config-gpu
```

### Custom Database

Use external PostgreSQL (RDS):

```yaml
db:
  dbname: "lablink_production"
  user: "lablink_admin"
  password: "${DB_PASSWORD}"
  host: "lablink-db.cluster-xxxxx.us-west-2.rds.amazonaws.com"
  port: 5432
```

## Configuration Best Practices

1. **Never commit secrets**: Use environment variables or AWS Secrets Manager
2. **Pin versions in production**: Use specific image tags, not `:latest`
3. **Document custom values**: Add comments explaining non-standard configurations
4. **Test configuration changes**: Validate with `terraform plan` before applying
5. **Use separate configs per environment**: Don't reuse dev configs in production

## Troubleshooting Configuration

### Config Not Loading

Check file location and syntax:
```bash
python -c "import yaml; print(yaml.safe_load(open('conf/config.yaml')))"
```

### Environment Variables Not Working

Verify export and check case sensitivity:
```bash
env | grep -i lablink
echo $DB_PASSWORD
```

### Terraform Variables Not Applied

Ensure `-var` flags are passed:
```bash
terraform plan -var="resource_suffix=prod"
```

## Next Steps

- **[Adapting LabLink](adapting.md)**: Customize for your research software
- **[Deployment](deployment.md)**: Deploy with your configuration
- **[Security](security.md)**: Secure your configuration values
