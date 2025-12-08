# Configuration Management Specification

## ADDED Requirements

### Requirement: Domain Format Validation
The system SHALL validate domain names to prevent malformed domains while allowing sub-subdomains for environment separation.

#### Scenario: Valid single-level subdomain accepted
- **GIVEN** a config with domain "lablink.sleap.ai"
- **WHEN** validation runs
- **THEN** validation passes

#### Scenario: Valid sub-subdomain accepted
- **GIVEN** a config with domain "test.lablink.sleap.ai"
- **WHEN** validation runs
- **THEN** validation passes

#### Scenario: Domain with leading dot rejected
- **GIVEN** a config with domain ".lablink.sleap.ai"
- **WHEN** validation runs
- **THEN** validation fails with error "Domain cannot start with a dot"

#### Scenario: Domain with trailing dot rejected
- **GIVEN** a config with domain "lablink.sleap.ai."
- **WHEN** validation runs
- **THEN** validation fails with error "Domain cannot end with a dot"

#### Scenario: Base domain without subdomain accepted
- **GIVEN** a config with domain "sleap.ai"
- **WHEN** validation runs
- **THEN** validation passes

### Requirement: SSL and DNS Dependency Validation
The system SHALL enforce that SSL (when enabled) requires DNS to be enabled, preventing invalid runtime configurations.

#### Scenario: SSL with DNS enabled passes validation
- **GIVEN** a config with ssl.provider="letsencrypt" and dns.enabled=true
- **WHEN** validation runs
- **THEN** validation passes

#### Scenario: SSL without DNS fails validation
- **GIVEN** a config with ssl.provider="letsencrypt" and dns.enabled=false
- **WHEN** validation runs
- **THEN** validation fails with error "SSL requires DNS to be enabled"

#### Scenario: No SSL with no DNS passes validation
- **GIVEN** a config with ssl.provider="none" and dns.enabled=false
- **WHEN** validation runs
- **THEN** validation passes

### Requirement: Provider-Specific Configuration Validation
The system SHALL validate that required configuration fields are present for each SSL provider.

#### Scenario: Let's Encrypt requires email
- **GIVEN** a config with ssl.provider="letsencrypt" and ssl.email=""
- **WHEN** validation runs
- **THEN** validation fails with error "Let's Encrypt requires email address"

#### Scenario: ACM requires certificate ARN
- **GIVEN** a config with ssl.provider="acm" and ssl.certificate_arn=""
- **WHEN** validation runs
- **THEN** validation fails with error "ACM provider requires certificate_arn"

#### Scenario: CloudFlare does not require email or ARN
- **GIVEN** a config with ssl.provider="cloudflare" and ssl.email="" and ssl.certificate_arn=""
- **WHEN** validation runs
- **THEN** validation passes

#### Scenario: CloudFlare requires external DNS management
- **GIVEN** a config with ssl.provider="cloudflare" and dns.terraform_managed=true
- **WHEN** validation runs
- **THEN** validation fails with error "CloudFlare SSL requires terraform_managed=false (external DNS)"

### Requirement: DNS Domain Required When Enabled
The system SHALL require a non-empty domain field when DNS is enabled.

#### Scenario: DNS enabled with domain passes
- **GIVEN** a config with dns.enabled=true and dns.domain="lablink.sleap.ai"
- **WHEN** validation runs
- **THEN** validation passes

#### Scenario: DNS enabled without domain fails
- **GIVEN** a config with dns.enabled=true and dns.domain=""
- **WHEN** validation runs
- **THEN** validation fails with error "DNS enabled requires non-empty domain field"

#### Scenario: DNS disabled with empty domain passes
- **GIVEN** a config with dns.enabled=false and dns.domain=""
- **WHEN** validation runs
- **THEN** validation passes

### Requirement: FQDN Computed by Infrastructure
The system SHALL compute the allocator FQDN during infrastructure deployment and provide it to the allocator service as the authoritative URL source.

#### Scenario: FQDN computed from DNS configuration
- **GIVEN** config with dns.enabled=true, dns.domain="lablink.sleap.ai", ssl.provider="letsencrypt"
- **WHEN** Terraform deploys infrastructure
- **THEN** computes ALLOCATOR_FQDN as "https://lablink.sleap.ai"
- **AND** passes ALLOCATOR_FQDN to allocator container as environment variable

#### Scenario: HTTP FQDN when SSL disabled
- **GIVEN** config with dns.enabled=true, dns.domain="lablink.sleap.ai", ssl.provider="none"
- **WHEN** Terraform deploys infrastructure
- **THEN** computes ALLOCATOR_FQDN as "http://lablink.sleap.ai"

#### Scenario: IP-only mode when DNS disabled
- **GIVEN** config with dns.enabled=false
- **WHEN** Terraform deploys infrastructure
- **THEN** computes ALLOCATOR_FQDN using allocator public IP
- **AND** uses http protocol

#### Scenario: Allocator uses FQDN from environment
- **GIVEN** ALLOCATOR_FQDN environment variable is set to "https://lablink.sleap.ai"
- **WHEN** allocator starts
- **THEN** allocator uses "https://lablink.sleap.ai" as its URL
- **AND** does not recompute URL from config
- **AND** logs indicate "Using ALLOCATOR_FQDN from environment: https://lablink.sleap.ai"

### Requirement: DNS Lifecycle Management
The system SHALL ensure DNS records are cleaned up when infrastructure is destroyed to prevent subdomain takeover vulnerabilities.

#### Scenario: Terraform-managed DNS records deleted on destroy
- **GIVEN** dns.terraform_managed=true
- **AND** infrastructure is deployed with DNS records created
- **WHEN** terraform destroy is executed
- **THEN** DNS records are deleted before other resources
- **AND** no dangling DNS records remain

#### Scenario: External DNS records not managed by Terraform
- **GIVEN** dns.terraform_managed=false
- **AND** infrastructure is deployed
- **WHEN** terraform destroy is executed
- **THEN** Terraform does not attempt to delete DNS records
- **AND** user is responsible for DNS cleanup

#### Scenario: Optional prevent_destroy protection for production
- **GIVEN** dns.terraform_managed=true
- **AND** prevent_destroy lifecycle policy is configured
- **WHEN** terraform destroy is attempted on production environment
- **THEN** Terraform blocks DNS record destruction
- **AND** provides clear error message requiring manual intervention

## MODIFIED Requirements

### Requirement: DNS Configuration Schema
The system SHALL support DNS configuration through a simplified schema that prevents common misconfiguration patterns while supporting flexible domain naming including sub-subdomains.

**Configuration Fields:**
- `enabled` (bool): Whether DNS is enabled
- `terraform_managed` (bool): Whether Terraform manages DNS records (true = Route53, false = external DNS like CloudFlare)
- `domain` (str): Full domain name (e.g., "lablink.sleap.ai", "test.lablink.sleap.ai")
- `zone_id` (str, optional): Route53 hosted zone ID for explicit zone targeting (auto-lookup if omitted)

**Removed Fields (BREAKING):**
- `app_name`: Replaced by complete domain in `domain` field
- `pattern`: Removed, use explicit domain instead
- `custom_subdomain`: Replaced by complete domain in `domain` field
- `create_zone`: Removed (zones should be pre-created and managed separately)

#### Scenario: Simplified DNS configuration with full domain
- **GIVEN** a config with dns.enabled=true and dns.domain="lablink.sleap.ai"
- **WHEN** DNS records are created
- **THEN** A record points to allocator IP with name "lablink.sleap.ai"

#### Scenario: Sub-subdomain for environment separation
- **GIVEN** a config with dns.enabled=true and dns.domain="test.lablink.sleap.ai"
- **WHEN** DNS records are created
- **THEN** A record points to allocator IP with name "test.lablink.sleap.ai"

#### Scenario: Optional zone_id for explicit zone targeting
- **GIVEN** a config with dns.zone_id="Z1234567890ABC"
- **AND** dns.terraform_managed=true
- **WHEN** Terraform looks up Route53 zone
- **THEN** uses provided zone_id without auto-lookup

#### Scenario: Zone auto-lookup when zone_id not provided
- **GIVEN** a config with dns.domain="lablink.sleap.ai" and dns.zone_id=""
- **AND** dns.terraform_managed=true
- **WHEN** Terraform looks up Route53 zone
- **THEN** queries Route53 for hosted zone matching "sleap.ai"

#### Scenario: External DNS provider configuration
- **GIVEN** dns.terraform_managed=false and dns.domain="lablink.sleap.ai"
- **WHEN** Terraform deploys infrastructure
- **THEN** Terraform outputs allocator IP for manual DNS configuration
- **AND** does not create or manage DNS records

### Requirement: SSL Configuration Schema
The system SHALL support multiple SSL providers through a unified configuration schema with proper validation.

**Configuration Fields:**
- `provider` (enum): SSL certificate provider
  - `"none"`: HTTP only, no SSL
  - `"letsencrypt"`: Automated SSL via Caddy + Let's Encrypt
  - `"cloudflare"`: CloudFlare proxy handles SSL (requires terraform_managed=false)
  - `"acm"`: AWS Certificate Manager (requires ALB)
- `email` (str): Email for Let's Encrypt notifications (required when provider="letsencrypt")
- `certificate_arn` (str, optional): ACM certificate ARN (required when provider="acm")

**Removed Fields (BREAKING):**
- `staging`: Removed (use dns.enabled=false + ssl.provider="none" for testing)

#### Scenario: Let's Encrypt SSL with email
- **GIVEN** ssl.provider="letsencrypt" and ssl.email="admin@sleap.ai"
- **AND** dns.enabled=true
- **WHEN** allocator starts
- **THEN** Caddy requests Let's Encrypt certificate
- **AND** sends notifications to admin@sleap.ai

#### Scenario: CloudFlare SSL without email
- **GIVEN** ssl.provider="cloudflare" and ssl.email=""
- **AND** dns.terraform_managed=false
- **WHEN** allocator starts
- **THEN** skips Caddy SSL setup (CloudFlare handles SSL)
- **AND** configures HTTP backend for CloudFlare proxy

#### Scenario: ACM SSL with certificate ARN
- **GIVEN** ssl.provider="acm" and ssl.certificate_arn="arn:aws:acm:us-west-2:123:certificate/abc"
- **AND** dns.enabled=true
- **WHEN** Terraform deploys infrastructure
- **THEN** creates ALB with ACM certificate attached
- **AND** ALB terminates SSL, forwards HTTP to allocator

#### Scenario: No SSL for testing
- **GIVEN** ssl.provider="none" and dns.enabled=false
- **WHEN** allocator starts
- **THEN** serves HTTP only on port 80
- **AND** no Caddy or ALB created

## REMOVED Requirements

### Requirement: DNS Pattern-Based Subdomain Construction
**Reason**: This pattern-based approach led to confusion, bugs, and allowed malformed domains like `.lablink.sleap.ai`. The concatenation of app_name + pattern + custom_subdomain created multiple ways to express the same configuration, making it difficult to understand and debug.

**Migration**: Use explicit `dns.domain` field with complete domain name.

**Old Pattern Mapping:**
- `pattern="auto"` + `app_name="lablink"` + environment → Use `domain="lablink.sleap.ai"` (prod) or `domain="test.lablink.sleap.ai"` (test)
- `pattern="app-only"` + `app_name="lablink"` → Use `domain="lablink.sleap.ai"`
- `pattern="custom"` + `custom_subdomain="dev"` + `domain="sleap.ai"` → Use `domain="dev.sleap.ai"`

### Requirement: SSL Staging Mode
**Reason**: The `ssl.staging` boolean added complexity without clear benefit. For unlimited testing, users should disable DNS and SSL entirely (IP-only mode), which is clearer than a "staging" boolean that modifies SSL behavior in non-obvious ways.

**Migration**:
- Old `ssl.staging=true` (HTTP-only for testing) → Use `dns.enabled=false` + `ssl.provider="none"`
- Old `ssl.staging=false` (production HTTPS) → Use `ssl.provider="letsencrypt"` with dns.enabled=true

### Requirement: Automatic DNS Zone Creation
**Reason**: Creating Route53 hosted zones during infrastructure deployment mixes concerns and can lead to accidental zone deletion. DNS zones should be managed separately as long-lived infrastructure.

**Migration**: Pre-create Route53 hosted zones manually or via separate Terraform module, then reference zone_id in config or rely on auto-lookup by domain.