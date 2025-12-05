# Simplify Domain and SSL Configuration

## Why

**Security vulnerability** identified: A security researcher found our test subdomain `test.lablink.sleap.ai` pointing to a decommissioned AWS IP (54.214.215.124), creating a subdomain takeover vulnerability (CVSS 8.2 - High Severity). The root cause is **dangling DNS records** after infrastructure destruction, not the use of sub-subdomains themselves.

**Current configuration problems:**
1. **No DNS cleanup on destroy**: Terraform-managed DNS records aren't guaranteed to be deleted when infrastructure is destroyed
2. **Invalid combinations permitted**: System allows SSL without DNS, leading to runtime failures like Caddy configured with `http://N/A`
3. **Configuration redundancy**: Multiple overlapping fields (`dns.app_name`, `dns.pattern`, `dns.custom_subdomain`) create confusion and bugs
4. **Subdomain concatenation bugs**: Empty `custom_subdomain` creates malformed FQDNs like `.lablink.sleap.ai`
5. **Dual source of truth**: Allocator constructs URLs from config while Terraform computes FQDNs, causing client connection failures (#212)
6. **No pre-deployment validation**: Misconfigured setups only fail at runtime

## What Changes

**BREAKING CHANGES:**

### 1. Simplified DNS Configuration Schema
- **REMOVE** redundant fields: `dns.app_name`, `dns.pattern`, `dns.custom_subdomain`, `dns.create_zone`
- **CHANGE** `dns.domain` to accept full domain (e.g., `lablink.sleap.ai`, `test.lablink.sleap.ai`)
  - **Note**: Sub-subdomains ARE allowed (common pattern for environments)
  - Validation ensures domain is non-empty when DNS enabled
- **CLARIFY** `dns.zone_id` as optional (auto-lookup if not provided)
- **KEEP** `dns.terraform_managed` flag (true = Terraform manages DNS, false = external DNS like CloudFlare)

### 2. DNS Lifecycle Management (Terraform)
- **ADD** Terraform lifecycle hooks to ensure DNS cleanup on destroy (when `terraform_managed=true`)
- **ADD** `prevent_destroy` option for production DNS records (configurable)
- **ADD** post-destroy verification (optional GitHub Action) to check for dangling DNS records

### 3. SSL Configuration Enhancement
- **CHANGE** `ssl.provider` enum values:
  - `"none"` - HTTP only, no SSL
  - `"letsencrypt"` - Free automated SSL via Caddy + Let's Encrypt
  - `"cloudflare"` - CloudFlare proxy handles SSL (certificate in CloudFlare)
  - `"acm"` - AWS Certificate Manager (purchased or validated cert, requires ALB)
- **REMOVE** `ssl.staging` (use `dns.enabled=false` + `ssl.provider="none"` for testing instead)
- **ADD** `ssl.certificate_arn` (optional, required when `provider="acm"`)
- **ENFORCE** validation: `ssl.provider != "none"` requires `dns.enabled=true`

### 4. FQDN Computed by Terraform
- **ADD** `ALLOCATOR_FQDN` environment variable computed by Terraform and passed to allocator container
- **CHANGE** Terraform to compute FQDN from config (based on `dns.domain` and `ssl.provider`)
- **CHANGE** Allocator to use `ALLOCATOR_FQDN` environment variable as authoritative source
- **FIX** Issue #212: Eliminates dual source of truth between Terraform-computed FQDN and allocator-computed URL

### 5. Enhanced Configuration Validation
- **ENHANCE** existing `lablink-validate-config` CLI with new validation rules:
  - SSL (non-"none") requires DNS enabled
  - DNS enabled requires non-empty `domain` field
  - Domain cannot start/end with dots (catches `.lablink.sleap.ai` bug)
  - CloudFlare SSL requires `terraform_managed=false` (external DNS)
  - Let's Encrypt requires valid email
  - ACM requires `certificate_arn` when `provider="acm"`
  - `terraform_managed=true` implies Route53 (document external DNS uses `terraform_managed=false`)
- **ADD** CI validation workflow to run on config changes (lablink-template repo)

### 6. Five Canonical Use Cases
Document and validate five explicit deployment patterns:

**Use Case 1: IP-only Testing (Local/Dev)**
```yaml
dns:
  enabled: false
ssl:
  provider: "none"
```

**Use Case 2: CloudFlare DNS + SSL (External DNS)**
```yaml
dns:
  enabled: true
  terraform_managed: false  # Manual CloudFlare DNS
  domain: "lablink.sleap.ai"  # Or "test.lablink.sleap.ai" for environments
ssl:
  provider: "cloudflare"
  email: ""  # Not used with CloudFlare
```

**Use Case 3: Route53 + Let's Encrypt (Terraform-managed DNS)**
```yaml
dns:
  enabled: true
  terraform_managed: true
  domain: "lablink.sleap.ai"  # Or "test.lablink.sleap.ai"
  zone_id: "Z1234567890ABC"  # Optional, auto-lookup if omitted
ssl:
  provider: "letsencrypt"
  email: "admin@sleap.ai"
```

**Use Case 4: Route53 + AWS Certificate Manager**
```yaml
dns:
  enabled: true
  terraform_managed: true
  domain: "lablink.sleap.ai"
  zone_id: "Z1234567890ABC"
ssl:
  provider: "acm"
  certificate_arn: "arn:aws:acm:us-west-2:123456789012:certificate/abc-123"
  email: ""  # Not used with ACM
```

**Use Case 5: Route53 + Let's Encrypt (Manual DNS)**
```yaml
dns:
  enabled: true
  terraform_managed: false  # Manual Route53 DNS records
  domain: "lablink.sleap.ai"
ssl:
  provider: "letsencrypt"
  email: "admin@sleap.ai"
```

## Impact

**Security:**
- **Primary fix**: Ensures DNS records are cleaned up when infrastructure is destroyed (prevents dangling records)
- Enforces valid SSL/DNS combinations through pre-deployment validation
- Supports enterprise SSL via AWS Certificate Manager
- Allows sub-subdomains (common pattern) while preventing malformed domains

**Affected Repositories:**
- `talmolab/lablink`: Configuration schema, enhanced validation CLI, allocator URL logic
- `talmolab/lablink-template`: Terraform DNS lifecycle, SSL/ALB logic, example configs, CI validation

**Affected Code (lablink repo):**
- `packages/allocator/src/lablink_allocator_service/conf/structured_config.py` - Config schema (BREAKING)
- `packages/allocator/src/lablink_allocator_service/conf/config.yaml` - Example config update
- `packages/allocator/src/lablink_allocator_service/validate_config.py` - Enhanced validation rules
- `packages/allocator/src/lablink_allocator_service/main.py` - FQDN environment variable support
- `packages/allocator/src/lablink_allocator_service/get_config.py` - Validation integration
- Tests for new validation logic

**Affected Code (lablink-template repo):**
- Terraform DNS configuration (remove pattern logic, use single domain, add lifecycle hooks)
- Terraform SSL/Caddy configuration (pass FQDN to container)
- Terraform ALB/ACM configuration (conditional creation when ssl.provider="acm")
- Example config files for all environments (dev, test, ci-test, prod)
- CI validation workflow (add lablink-validate-config step)
- Optional post-destroy DNS verification workflow

**Migration Path:**
- Existing deployments must update configs before next allocator release
- Migration guide provided with examples for each use case
- Validation errors provide clear migration instructions
- Sub-subdomains continue to work (no breaking change in functionality, only config schema)

**Related Issues:**
- Fixes: talmolab/lablink-template#7 (Simplify DNS and SSL)
- Fixes: talmolab/lablink#200 (Subdomain bug persists - empty subdomain creates `.lablink.sleap.ai`)
- Fixes: talmolab/lablink#212 (FQDN environment variable)
- Implements: talmolab/lablink-template#12 (Config validation in CI)
- Addresses security disclosure: Subdomain takeover via dangling DNS records

**Release Plan:**
1. Merge changes to lablink package (this repo)
2. Update tests for new validation rules
3. Release new allocator package version to PyPI (breaking change, bump minor version)
4. Update lablink-template with new Terraform logic (DNS lifecycle, ACM/ALB support)
5. Document migration guide in both repos with all five use cases
6. Notify users of breaking changes via GitHub release notes

**Notes on ACM Support:**
- ACM certificates require Application Load Balancer (ALB) or CloudFront
- Terraform will conditionally create ALB when `ssl.provider="acm"`
- ALB adds cost (~$16/month + data transfer) vs Caddy (free)
- Let's Encrypt remains the default recommendation for cost-effective SSL