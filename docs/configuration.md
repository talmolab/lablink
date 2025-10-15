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
  ami_id: "ami-067cc81f948e50e06"
  repository: "https://github.com/talmolab/sleap-tutorial-data.git"
  software: "sleap"

app:
  admin_user: "admin"
  admin_password: "PLACEHOLDER_ADMIN_PASSWORD"  # Injected from GitHub secret at deploy time
  region: "us-west-2"

bucket_name: "tf-state-lablink-allocator-bucket"
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
| `password` | string | `PLACEHOLDER_DB_PASSWORD` | Database password (injected from GitHub secret) |
| `host` | string | `localhost` | Database host |
| `port` | int | `5432` | PostgreSQL port |
| `table_name` | string | `vms` | VM table name |
| `message_channel` | string | `vm_updates` | PostgreSQL NOTIFY channel |

!!! warning "Production Security"
    Configure `DB_PASSWORD` secret for GitHub Actions deployments, or manually replace the placeholder. See [Security](security.md#database-password).

### Machine Options (`machine`)

Configuration for client VM specifications. **These are the key options for adapting LabLink to your research software.**

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `machine_type` | string | `g4dn.xlarge` | AWS EC2 instance type |
| `image` | string | `ghcr.io/talmolab/lablink-client-base-image:latest` | Docker image for client container |
| `ami_id` | string | `ami-067cc81f948e50e06` | Amazon Machine Image (Ubuntu 20.04 + Docker) |
| `repository` | string (optional) | `https://github.com/talmolab/sleap-tutorial-data.git` | Git repository to clone on VM |
| `software` | string | `sleap` | Software identifier (used by client) |

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

**Default**: `ami-067cc81f948e50e06` (Ubuntu 20.04 + Docker in us-west-2)

The Amazon Machine Image determines the OS and pre-installed software. You may need different AMIs for:

- Different AWS regions (AMI IDs are region-specific)
- Different OS versions
- Custom pre-configured images

**Find AMIs**:
```bash
aws ec2 describe-images \
  --owners 099720109477 \
  --filters "Name=name,Values=ubuntu/images/hvm-ssd/ubuntu-focal-20.04-amd64-server-*" \
  --query 'Images[*].[ImageId,Name,CreationDate]' \
  --output table
```

#### Repository

**Default**: `https://github.com/talmolab/sleap-tutorial-data.git`

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

### Application Options (`app`)

General application settings.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `admin_user` | string | `admin` | Admin username for web UI |
| `admin_password` | string | `PLACEHOLDER_ADMIN_PASSWORD` | Admin password (injected from GitHub secret) |
| `region` | string | `us-west-2` | AWS region for deployments |

!!! danger "Configure Passwords"
    Configure `ADMIN_PASSWORD` secret for GitHub Actions deployments, or manually replace the placeholder. See [Security](security.md#change-default-passwords).

### Allocator Options (`allocator`)

Client configuration for connecting to allocator.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `host` | string | `localhost` | Allocator hostname or IP |
| `port` | int | `80` | Allocator port |

### DNS Options (`dns`)

Controls DNS configuration for allocator hostname.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `enabled` | boolean | `false` | Enable DNS-based URLs |
| `terraform_managed` | boolean | `false` | Let Terraform manage Route 53 records |
| `domain` | string | `""` | Your Route 53 hosted zone domain |
| `zone_id` | string | `""` | Route 53 zone ID (optional, skips lookup if provided) |
| `app_name` | string | `""` | Application name for auto pattern |
| `pattern` | string | `"auto"` | DNS pattern: `auto` or `custom` |
| `custom_subdomain` | string | `""` | Custom subdomain for custom pattern |
| `create_zone` | boolean | `false` | Create new Route 53 zone |

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
| `provider` | string | `"letsencrypt"` | SSL provider: `letsencrypt`, `cloudflare`, or `none` |
| `email` | string | `""` | Email for Let's Encrypt notifications |
| `staging` | boolean | `false` | HTTP-only mode for testing (unlimited deployments) |

#### SSL Providers

**`letsencrypt`** - Automatic SSL via Caddy + Let's Encrypt

- Staging mode (`staging: true`): HTTP only, unlimited deployments
- Production mode (`staging: false`): HTTPS with trusted certificates

**`cloudflare`** - CloudFlare proxy handles SSL

- Requires CloudFlare DNS configuration
- Not affected by `staging` setting

**`none`** - No SSL, HTTP only

- Similar to staging mode but explicit

#### Staging vs Production Mode

**Staging Mode** (`staging: true`)

Use for testing and development:

- Serves HTTP only on port 80 (port 443 closed)
- Unlimited deployments per day
- No SSL certificate issuance delays
- **No encryption** - all traffic is plaintext
- Browser shows "Not Secure" warning
- May require clearing browser HSTS cache (see [Troubleshooting](troubleshooting.md#browser-cannot-access-http-staging-mode))

Configuration example:
```yaml
ssl:
  provider: "letsencrypt"
  email: "admin@example.com"
  staging: true
```

**Production Mode** (`staging: false`)

Use for production deployments:

- HTTPS with trusted Let's Encrypt certificates
- Browser shows secure padlock
- Full TLS 1.3 encryption
- Automatic HTTP → HTTPS redirects
- Rate limited (5 duplicate certificates per week)
- Certificate issuance takes 30-60 seconds

Configuration example:
```yaml
ssl:
  provider: "letsencrypt"
  email: "admin@example.com"  # Receives cert expiry notifications
  staging: false
```

#### Browser Access

**With staging mode:**

1. Type `http://` explicitly in address bar (e.g., `http://test.lablink.sleap.ai`)
2. Clear HSTS cache if you previously accessed via HTTPS
3. Expect "Not Secure" warning (this is normal)

Alternatives:
- Use incognito/private browsing
- Access via IP: `http://<allocator-ip>`
- Use curl: `curl http://test.lablink.sleap.ai`

**With production mode:**

Access via `https://your-domain.com` - browser shows secure padlock.

#### Let's Encrypt Rate Limits

Production mode is subject to Let's Encrypt limits:

- 50 certificates per domain per week
- **5 duplicate certificates per week** (same hostnames)
- 300 pending authorizations per account

Use staging mode for frequent testing to avoid these limits.

**Warning:** Staging mode serves unencrypted HTTP. Never use for production or sensitive data. See [Security](security.md#staging-mode-security).

### Bucket Name

**Option**: `bucket_name`
**Default**: `tf-state-lablink-allocator-bucket`

S3 bucket for Terraform state storage. Must be globally unique.

## Overriding Configuration

### Method 1: Edit YAML Files

Directly modify the configuration files:

```bash
nano lablink-infrastructure/config/config.yaml
```

### Method 2: Environment Variables

Override specific values without modifying files:

```bash
export DB_PASSWORD=my_secure_password
export ADMIN_PASSWORD=my_admin_password
export AWS_REGION=us-east-1
```

### Method 3: Hydra Command-Line Overrides

When running Python directly:

```bash
python main.py db.password=my_password app.region=us-east-1
```

### Method 4: Docker Environment Variables

Pass environment variables to Docker containers:

```bash
docker run -d \
  -e DB_PASSWORD=secure_password \
  -e ADMIN_PASSWORD=admin_password \
  -e AWS_REGION=us-east-1 \
  -p 5000:5000 \
  ghcr.io/talmolab/lablink-allocator-image:latest
```

!!! warning "Config Validation and Custom Filenames"
    The allocator supports `CONFIG_NAME` environment variable to override the config filename. However, the validation CLI (`lablink-validate-config`) requires the filename to be `config.yaml` to enable strict schema checking. If you override `CONFIG_NAME` to use a different filename, validation will not perform strict schema checks and unknown keys may not be caught until runtime.

### Method 5: Terraform Variables

Override during infrastructure deployment:

```bash
terraform apply \
  -var="allocator_image_tag=v1.0.0" \
  -var="resource_suffix=prod"
```

## Configuration for Different Environments

### Development

**Use Case**: Local testing, experimentation

```yaml
db:
  password: "simple_dev_password"

machine:
  machine_type: "t2.micro"  # Cheaper for testing
  image: "ghcr.io/talmolab/lablink-client-base-image:linux-amd64-test"

app:
  region: "us-west-2"
```

### Test/Staging

**Use Case**: Pre-production validation

```yaml
db:
  password: "${DB_PASSWORD}"  # From environment variable

machine:
  machine_type: "g4dn.xlarge"
  image: "ghcr.io/talmolab/lablink-client-base-image:linux-amd64-test"

app:
  admin_password: "${ADMIN_PASSWORD}"
  region: "us-west-2"
```

### Production

**Use Case**: Production workloads

```yaml
db:
  password: "${DB_PASSWORD}"  # From Secrets Manager
  host: "lablink-db.xxxxx.us-west-2.rds.amazonaws.com"  # RDS instance

machine:
  machine_type: "g5.2xlarge"
  image: "ghcr.io/talmolab/lablink-client-base-image:v1.0.0"  # Pinned version

app:
  admin_password: "${ADMIN_PASSWORD}"  # From Secrets Manager
  region: "us-west-2"

bucket_name: "tf-state-lablink-prod"
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
  ami_id: "ami-067cc81f948e50e06"
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