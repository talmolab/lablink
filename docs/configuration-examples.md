# Configuration Examples

Complete, copy-paste-ready `config.yaml` files for common deployment scenarios. For field-by-field reference, see [Configuration](configuration.md).

!!! info "Source"
    These examples are maintained in the [lablink-template](https://github.com/talmolab/lablink-template) repository under `lablink-infrastructure/config/`.

## Choosing a Configuration

| Scenario | SSL | DNS Required | Rate Limits | Extra Cost | Complexity |
|----------|-----|-------------|-------------|------------|------------|
| [IP Only](#ip-only) | None | No | None | None | Simplest |
| [Let's Encrypt (Terraform DNS)](#caddy-ssl) | Auto via Caddy | Route53 | 5 certs/domain/week | None | Medium |
| [Let's Encrypt (Manual DNS)](#caddy-ssl) | Auto via Caddy | Route53 (manual) | 5 certs/domain/week | None | Medium |
| [CloudFlare](#caddy-ssl) | CloudFlare proxy | CloudFlare | None | None | Medium |
| [ACM + ALB](#alb-with-acm) | AWS-managed | Route53 | None | ~$20/month | Higher |

**Quick decision guide:**

- **No domain?** Use [IP Only](#ip-only)
- **Have a domain + want free auto-SSL?** Use [Let's Encrypt](#caddy-ssl) (pick Terraform-managed vs manual DNS)
- **Domain in CloudFlare?** Use [CloudFlare](#caddy-ssl)
- **Want enterprise-grade load balancing?** Use [ACM + ALB](#alb-with-acm)

## IP Only

Access the allocator via public IP address over HTTP. No domain or SSL required.

!!! tip "No rate limits"
    This is the simplest setup and has no certificate issuance limits. Perfect for frequent testing and development.

**Prerequisites:** None

**Access URL:** `http://<ALLOCATOR_IP>:5000`

```yaml
# LabLink Configuration: IP-Only (No DNS, No SSL)
# Access allocator via public IP address over HTTP
#
# Setup:
# 1. Run setup script: ./scripts/setup-aws-infrastructure.sh
# 2. Deploy infrastructure
# 3. Note allocator IP from Terraform output

db:
  dbname: "lablink_db"
  user: "lablink"
  password: "PLACEHOLDER_DB_PASSWORD"
  host: "localhost"
  port: 5432
  table_name: "vms"
  message_channel: "vm_updates"

machine:
  machine_type: "g4dn.xlarge"
  image: "ghcr.io/talmolab/lablink-client-base-image:linux-amd64-latest-test"
  ami_id: "ami-0601752c11b394251"  # us-west-2
  repository: "https://github.com/talmolab/sleap-tutorial-data.git"
  software: "sleap"
  extension: "slp"

allocator:
  image_tag: "linux-amd64-latest-test"

app:
  admin_user: "admin"
  admin_password: "PLACEHOLDER_ADMIN_PASSWORD"
  region: "us-west-2"

dns:
  enabled: false  # No DNS - use IP address only
  terraform_managed: false
  domain: ""
  zone_id: ""

eip:
  strategy: "dynamic"
  tag_name: "lablink-eip"

ssl:
  provider: "none"  # No SSL - HTTP only
  email: ""
  certificate_arn: ""

startup_script:
  enabled: false
  path: "config/custom-startup.sh"
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

bucket_name: "tf-state-lablink-YOURORG"
```

## Caddy SSL

Use Caddy as a reverse proxy with automatic SSL. Three options depending on your DNS provider and management preference.

=== "Let's Encrypt (Terraform DNS)"

    Route53 DNS records managed automatically by Terraform. Caddy obtains Let's Encrypt certificates.

    !!! warning "Rate limits"
        Let's Encrypt allows **5 certificates per exact domain every 7 days**. Each `terraform apply` triggers a new certificate. For frequent testing, use [CloudFlare](#caddy-ssl) or [IP Only](#ip-only) instead. Monitor usage at `https://crt.sh/?q=your-domain.com`.

    **Prerequisites:**

    - Route53 hosted zone created (e.g., `lablink.example.com`)
    - Domain nameservers pointed to Route53

    **Access URL:** `https://test.lablink.example.com`

    ```yaml
    # LabLink Configuration: Route53 + Let's Encrypt (Terraform-managed DNS)
    #
    # Setup:
    # 1. Run setup script: ./scripts/setup-aws-infrastructure.sh
    # 2. Terraform will create A record automatically
    # 3. Caddy will obtain Let's Encrypt certificate on first access

    db:
      dbname: "lablink_db"
      user: "lablink"
      password: "PLACEHOLDER_DB_PASSWORD"
      host: "localhost"
      port: 5432
      table_name: "vms"
      message_channel: "vm_updates"

    machine:
      machine_type: "g4dn.xlarge"
      image: "ghcr.io/talmolab/lablink-client-base-image:linux-amd64-latest-test"
      ami_id: "ami-0601752c11b394251"  # us-west-2
      repository: "https://github.com/talmolab/sleap-tutorial-data.git"
      software: "sleap"
      extension: "slp"

    allocator:
      image_tag: "linux-amd64-latest-test"

    app:
      admin_user: "admin"
      admin_password: "PLACEHOLDER_ADMIN_PASSWORD"
      region: "us-west-2"

    dns:
      enabled: true  # Route53 DNS enabled
      terraform_managed: true  # Terraform creates/destroys A record
      domain: "test.lablink.example.com"  # Full domain (can be sub-subdomain)
      zone_id: ""  # Auto-lookup hosted zone

    eip:
      strategy: "persistent"
      tag_name: "lablink-eip"

    ssl:
      provider: "letsencrypt"  # Caddy auto-SSL with Let's Encrypt
      email: "admin@example.com"  # Required for Let's Encrypt notifications
      certificate_arn: ""

    startup_script:
      enabled: false
      path: "config/custom-startup.sh"
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

    bucket_name: "tf-state-lablink-YOURORG"
    ```

=== "Let's Encrypt (Manual DNS)"

    Route53 DNS with manually created A records. Useful when you don't want Terraform managing DNS records.

    !!! warning "Rate limits"
        Same Let's Encrypt rate limits apply. See the Terraform DNS tab for details.

    **Prerequisites:**

    - Route53 hosted zone created
    - Manually create A record: `test.lablink.example.com` pointing to the allocator EIP

    **Setup:**

    1. Deploy infrastructure (get allocator EIP from output)
    2. Manually create A record in Route53 console
    3. Wait for DNS propagation
    4. Access allocator URL (Caddy obtains Let's Encrypt cert)

    **Access URL:** `https://test.lablink.example.com`

    ```yaml
    # LabLink Configuration: Route53 + Let's Encrypt (Manual DNS)
    #
    # Setup:
    # 1. Deploy infrastructure (get allocator EIP from output)
    # 2. Manually create A record in Route53 console
    # 3. Wait for DNS propagation
    # 4. Access allocator URL (Caddy obtains Let's Encrypt cert)

    db:
      dbname: "lablink_db"
      user: "lablink"
      password: "PLACEHOLDER_DB_PASSWORD"
      host: "localhost"
      port: 5432
      table_name: "vms"
      message_channel: "vm_updates"

    machine:
      machine_type: "g4dn.xlarge"
      image: "ghcr.io/talmolab/lablink-client-base-image:linux-amd64-latest-test"
      ami_id: "ami-0601752c11b394251"  # us-west-2
      repository: "https://github.com/talmolab/sleap-tutorial-data.git"
      software: "sleap"
      extension: "slp"

    allocator:
      image_tag: "linux-amd64-latest-test"

    app:
      admin_user: "admin"
      admin_password: "PLACEHOLDER_ADMIN_PASSWORD"
      region: "us-west-2"

    dns:
      enabled: true  # DNS expected (used for SSL certificate domain)
      terraform_managed: false  # Manual DNS - YOU create A record in Route53 console
      domain: "test.lablink.example.com"  # Full domain
      zone_id: ""  # Not needed for manual DNS

    eip:
      strategy: "persistent"
      tag_name: "lablink-eip"

    ssl:
      provider: "letsencrypt"  # Caddy auto-SSL with Let's Encrypt
      email: "admin@example.com"  # Required for Let's Encrypt notifications
      certificate_arn: ""

    startup_script:
      enabled: false
      path: "config/custom-startup.sh"
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

    bucket_name: "tf-state-lablink-YOURORG"
    ```

=== "CloudFlare"

    Use CloudFlare for DNS management and SSL termination. No rate limits on certificate issuance.

    !!! tip "No rate limits"
        CloudFlare SSL has no certificate issuance limits. Ideal for frequent testing and redeployments.

    **Prerequisites:**

    - Domain registered and managed in CloudFlare
    - CloudFlare proxy enabled (orange cloud icon)

    **Setup:**

    1. Deploy infrastructure (note allocator IP from output)
    2. Create A record in CloudFlare: `lablink.example.com` pointing to allocator IP
    3. Enable CloudFlare proxy (orange cloud)
    4. Set SSL/TLS mode to **Full** (not Strict)

    **Access URL:** `https://lablink.example.com`

    ```yaml
    # LabLink Configuration: CloudFlare DNS + SSL
    #
    # Setup:
    # 1. Deploy infrastructure (note allocator IP from output)
    # 2. Create A record in CloudFlare pointing to allocator IP
    # 3. Enable CloudFlare proxy (orange cloud)
    # 4. SSL/TLS mode: Full (not Strict)

    db:
      dbname: "lablink_db"
      user: "lablink"
      password: "PLACEHOLDER_DB_PASSWORD"
      host: "localhost"
      port: 5432
      table_name: "vms"
      message_channel: "vm_updates"

    machine:
      machine_type: "g4dn.xlarge"
      image: "ghcr.io/talmolab/lablink-client-base-image:linux-amd64-latest-test"
      ami_id: "ami-0601752c11b394251"  # us-west-2
      repository: "https://github.com/talmolab/sleap-tutorial-data.git"
      software: "sleap"
      extension: "slp"

    allocator:
      image_tag: "linux-amd64-latest-test"

    app:
      admin_user: "admin"
      admin_password: "PLACEHOLDER_ADMIN_PASSWORD"
      region: "us-west-2"

    dns:
      enabled: true  # DNS required for SSL (managed in CloudFlare, not Route53)
      terraform_managed: false  # DNS records created manually in CloudFlare
      domain: "lablink.example.com"  # Used for Caddyfile configuration
      zone_id: ""  # Not used (CloudFlare manages DNS)

    eip:
      strategy: "persistent"
      tag_name: "lablink-eip"

    ssl:
      provider: "cloudflare"  # CloudFlare handles SSL termination
      email: ""
      certificate_arn: ""

    startup_script:
      enabled: false
      path: "config/custom-startup.sh"
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

    bucket_name: "tf-state-lablink-YOURORG"
    ```

## ALB with ACM

Use AWS Application Load Balancer with ACM-managed SSL certificates. Enterprise-grade setup with no rate limits.

!!! note "Additional cost"
    ALB adds approximately **~$20/month** but provides enterprise-grade SSL termination and scalability.

**Prerequisites:**

1. Route53 hosted zone created
2. ACM certificate requested and validated for your domain
3. Certificate ARN obtained from ACM console

**Setup:**

1. Request ACM certificate in ACM console (same region as deployment, e.g., `us-west-2`)
2. Validate certificate (DNS or email validation)
3. Copy certificate ARN to `ssl.certificate_arn` below
4. Deploy infrastructure (Terraform creates ALB with HTTPS listener)

**Access URL:** `https://lablink.example.com`

```yaml
# LabLink Configuration: Route53 + ACM (AWS Certificate Manager)
# Enterprise-grade SSL with ALB
#
# Setup:
# 1. Request ACM certificate in ACM console (us-west-2)
# 2. Validate certificate (DNS or email validation)
# 3. Copy certificate ARN to ssl.certificate_arn below
# 4. Deploy infrastructure (Terraform creates ALB with HTTPS listener)

db:
  dbname: "lablink_db"
  user: "lablink"
  password: "PLACEHOLDER_DB_PASSWORD"
  host: "localhost"
  port: 5432
  table_name: "vms"
  message_channel: "vm_updates"

machine:
  machine_type: "g4dn.xlarge"
  image: "ghcr.io/talmolab/lablink-client-base-image:linux-amd64-latest-test"
  ami_id: "ami-0601752c11b394251"  # us-west-2
  repository: "https://github.com/talmolab/sleap-tutorial-data.git"
  software: "sleap"
  extension: "slp"

allocator:
  image_tag: "linux-amd64-latest-test"

app:
  admin_user: "admin"
  admin_password: "PLACEHOLDER_ADMIN_PASSWORD"
  region: "us-west-2"

dns:
  enabled: true  # Route53 DNS enabled
  terraform_managed: true  # Terraform creates/destroys A record (alias to ALB)
  domain: "lablink.example.com"  # Full domain
  zone_id: ""  # Auto-lookup hosted zone

eip:
  strategy: "persistent"
  tag_name: "lablink-eip"

ssl:
  provider: "acm"  # AWS Certificate Manager via ALB
  email: ""  # Not needed for ACM
  certificate_arn: "arn:aws:acm:us-west-2:123456789012:certificate/abcd1234-5678-90ab-cdef-EXAMPLE11111"  # REPLACE with your ACM cert ARN

startup_script:
  enabled: false
  path: "config/custom-startup.sh"
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

bucket_name: "tf-state-lablink-YOURORG"
```

## Environment-Specific Configs

These examples show how to tune configurations for different environments.

=== "Development"

    Minimal setup for local development with local Terraform state. Uses cheaper instance types and dynamic EIPs.

    ```yaml
    # LabLink Development Configuration
    # Uses local Terraform state, no DNS/SSL, cheaper instances
    #
    # Usage:
    #   cp config/dev.example.yaml config/config.yaml
    #   cd lablink-infrastructure
    #   ../scripts/init-terraform.sh dev
    #   terraform apply -var="resource_suffix=dev"

    db:
      dbname: "lablink_db"
      user: "lablink"
      password: "PLACEHOLDER_DB_PASSWORD"
      host: "localhost"
      port: 5432
      table_name: "vms"
      message_channel: "vm_updates"

    machine:
      machine_type: "t3.medium"  # Smaller, cheaper for testing
      image: "ghcr.io/talmolab/lablink-client-base-image:linux-amd64-latest-test"
      ami_id: "ami-0601752c11b394251"
      repository: "https://github.com/talmolab/sleap-tutorial-data.git"
      software: "sleap"
      extension: "slp"

    allocator:
      image_tag: "linux-amd64-latest-test"

    app:
      admin_user: "admin"
      admin_password: "PLACEHOLDER_ADMIN_PASSWORD"
      region: "us-west-2"

    dns:
      enabled: false
      terraform_managed: false
      domain: "example.com"
      zone_id: ""

    eip:
      strategy: "dynamic"  # Don't reuse EIPs for dev
      tag_name: "lablink-eip-dev-YOURNAME"  # Replace YOURNAME

    ssl:
      provider: "none"
      email: "dev@example.com"
      certificate_arn: ""

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

    # Dev uses local state - this value is not used
    bucket_name: "not-used-for-dev-environment"
    ```

=== "Production"

    Full production setup with pinned image versions, monitoring enabled, and persistent EIPs.

    !!! danger "Pin your versions"
        Always use specific version tags (e.g., `v1.0.0`) in production, never `latest` or `latest-test`.

    ```yaml
    # LabLink Production Configuration
    # S3 backend, pinned versions, monitoring enabled
    #
    # Usage:
    #   cp config/prod.example.yaml config/config.yaml
    #   ./scripts/setup-aws-infrastructure.sh
    #   cd lablink-infrastructure
    #   ../scripts/init-terraform.sh prod
    #   terraform apply -var="resource_suffix=prod"

    db:
      dbname: "lablink_db"
      user: "lablink"
      password: "PLACEHOLDER_DB_PASSWORD"
      host: "localhost"
      port: 5432
      table_name: "vms"
      message_channel: "vm_updates"

    machine:
      machine_type: "g4dn.xlarge"  # GPU instance for ML workloads
      image: "ghcr.io/talmolab/lablink-client-base-image:linux-amd64-v1.0.0"  # PINNED
      ami_id: "ami-0601752c11b394251"
      repository: "https://github.com/YOUR_ORG/YOUR_PROD_REPO.git"
      software: "sleap"
      extension: "slp"

    allocator:
      image_tag: "linux-amd64-v1.0.0"  # PINNED - update deliberately

    app:
      admin_user: "admin"
      admin_password: "PLACEHOLDER_ADMIN_PASSWORD"
      region: "us-west-2"

    dns:
      enabled: true
      terraform_managed: true
      domain: "example.com"
      zone_id: ""

    eip:
      strategy: "persistent"  # Keep IP across redeploys
      tag_name: "lablink-eip"

    ssl:
      provider: "letsencrypt"
      email: "admin@example.com"
      certificate_arn: ""

    startup_script:
      enabled: false
      path: ""
      on_error: "continue"

    monitoring:
      enabled: true  # Enable monitoring for production
      email: "admin@example.com"  # Alert notifications
      thresholds:
        max_instances_per_5min: 10
        max_terminations_per_5min: 20
        max_unauthorized_calls_per_15min: 5
      budget:
        enabled: false
        monthly_budget_usd: 500
      cloudtrail:
        retention_days: 90

    bucket_name: "tf-state-lablink-YOURORG-prod"
    ```

=== "CI Test"

    For template maintainers testing infrastructure changes. Uses separate AWS infrastructure from production.

    ```yaml
    # LabLink CI-Test Configuration
    # Template maintainers only - tests the template repo infrastructure
    #
    # Usage:
    #   cp config/ci-test.example.yaml config/config.yaml
    #   ./scripts/setup-aws-infrastructure.sh
    #   cd lablink-infrastructure
    #   ../scripts/init-terraform.sh ci-test
    #   terraform apply -var="resource_suffix=ci-test"

    db:
      dbname: "lablink_db"
      user: "lablink"
      password: "PLACEHOLDER_DB_PASSWORD"
      host: "localhost"
      port: 5432
      table_name: "vms"
      message_channel: "vm_updates"

    machine:
      machine_type: "t3.medium"  # Cheaper for template testing
      image: "ghcr.io/talmolab/lablink-client-base-image:linux-amd64-latest-test"
      ami_id: "ami-0601752c11b394251"
      repository: "https://github.com/talmolab/sleap-tutorial-data.git"
      software: "sleap"
      extension: "slp"

    allocator:
      image_tag: "linux-amd64-latest-test"

    app:
      admin_user: "admin"
      admin_password: "PLACEHOLDER_ADMIN_PASSWORD"
      region: "us-west-2"

    dns:
      enabled: true
      terraform_managed: true
      domain: "lablink-template-testing.com"
      zone_id: ""

    eip:
      strategy: "dynamic"
      tag_name: "lablink-eip"

    ssl:
      provider: "letsencrypt"
      email: "admin@example.com"
      certificate_arn: ""

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

    bucket_name: "tf-state-lablink-template-testing"
    ```

## Key Differences Between Examples

The table below highlights the fields that differ across configurations. All other fields are identical.

| Field | IP Only | Let's Encrypt | CloudFlare | ACM | Dev | Production |
|-------|---------|--------------|------------|-----|-----|------------|
| `dns.enabled` | `false` | `true` | `true` | `true` | `false` | `true` |
| `dns.terraform_managed` | `false` | `true` / `false` | `false` | `true` | `false` | `true` |
| `eip.strategy` | `dynamic` | `persistent` | `persistent` | `persistent` | `dynamic` | `persistent` |
| `ssl.provider` | `none` | `letsencrypt` | `cloudflare` | `acm` | `none` | `letsencrypt` |
| `ssl.email` | — | required | — | — | — | required |
| `ssl.certificate_arn` | — | — | — | required | — | — |
| `machine.machine_type` | `g4dn.xlarge` | `g4dn.xlarge` | `g4dn.xlarge` | `g4dn.xlarge` | `t3.medium` | `g4dn.xlarge` |
| `monitoring.enabled` | `false` | `false` | `false` | `false` | `false` | `true` |

## Next Steps

- **[Configuration](configuration.md)**: Field-by-field reference for all options
- **[DNS Configuration](dns-configuration.md)**: Detailed DNS setup instructions
- **[Deployment](deployment.md)**: Deploy with your configuration
- **[Security](security.md)**: Secure your configuration values
