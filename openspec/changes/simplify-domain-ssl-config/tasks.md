# Implementation Tasks

## 1. Configuration Schema Updates (lablink repo)
- [ ] 1.1 Update `DNSConfig` dataclass in `structured_config.py`
  - [ ] Remove: `app_name`, `pattern`, `custom_subdomain`, `create_zone`
  - [ ] Keep: `enabled`, `terraform_managed`, `domain`, `zone_id`
  - [ ] Update docstrings with new behavior
- [ ] 1.2 Update `SSLConfig` dataclass in `structured_config.py`
  - [ ] Change `provider` enum: `"none"`, `"letsencrypt"`, `"cloudflare"`, `"acm"`
  - [ ] Remove: `staging` field
  - [ ] Add: `certificate_arn` field (optional, for ACM)
  - [ ] Update docstrings
- [ ] 1.3 Update example `config.yaml` with new schema
  - [ ] Use single `domain` field
  - [ ] Remove deprecated fields
  - [ ] Add comments explaining new structure

## 2. Validation Logic Enhancement (lablink repo)
- [ ] 2.1 Create domain validator function
  - [ ] Validate domain format (no sub-subdomains)
  - [ ] Reject domains with multiple dots in subdomain part
  - [ ] Allow single-level subdomains (e.g., `lablink.sleap.ai`)
- [ ] 2.2 Enhance `validate_config.py` with new rules
  - [ ] SSL non-"none" requires DNS enabled
  - [ ] DNS enabled requires non-empty domain
  - [ ] CloudFlare SSL requires terraform_managed=false
  - [ ] Let's Encrypt requires valid email
  - [ ] ACM requires certificate_arn when provider="acm"
  - [ ] Domain format validation (no sub-subdomains)
- [ ] 2.3 Add validation hook in `get_config.py`
  - [ ] Call validators after config load
  - [ ] Provide clear error messages on validation failure

## 3. Allocator FQDN Support (lablink repo)
- [ ] 3.1 Update `main.py` to read `ALLOCATOR_FQDN` environment variable
  - [ ] Priority: ALLOCATOR_FQDN > DNS config > IP fallback
  - [ ] Log which URL source is being used
- [ ] 3.2 Update URL construction logic
  - [ ] Remove pattern-based concatenation
  - [ ] Use simple domain from config or FQDN from env
- [ ] 3.3 Update client connection logic
  - [ ] Ensure clients can reach allocator via FQDN
  - [ ] Update logging for debugging connection issues

## 4. Testing (lablink repo)
- [ ] 4.1 Unit tests for domain validator
  - [ ] Valid single-level subdomains pass
  - [ ] Sub-subdomains rejected
  - [ ] Edge cases (no dots, trailing dots, etc.)
- [ ] 4.2 Unit tests for enhanced validation
  - [ ] Test all five canonical use cases validate correctly
  - [ ] Test invalid combinations rejected
  - [ ] Test error messages are clear
- [ ] 4.3 Integration tests for FQDN environment variable
  - [ ] Test FQDN takes precedence over config
  - [ ] Test fallback to config domain
  - [ ] Test fallback to IP-only mode
- [ ] 4.4 Update existing tests for schema changes
  - [ ] Update test configs to new schema
  - [ ] Remove tests for deprecated fields

## 5. Documentation (lablink repo)
- [ ] 5.1 Update CLAUDE.md with new configuration structure
- [ ] 5.2 Create migration guide document
  - [ ] Old schema → new schema mapping
  - [ ] Examples for each use case
  - [ ] Common migration scenarios
- [ ] 5.3 Update docs/ with new configuration guide
  - [ ] Document all five use cases
  - [ ] Add ACM setup instructions
  - [ ] Add troubleshooting section

## 6. Package Release (lablink repo)
- [ ] 6.1 Bump allocator package version (breaking change)
  - [ ] Update `pyproject.toml` version
  - [ ] Update CHANGELOG.md
- [ ] 6.2 Test package build locally
  - [ ] Build with `uv build`
  - [ ] Test installation from built package
- [ ] 6.3 Create git tag and push
- [ ] 6.4 Publish to PyPI via workflow
- [ ] 6.5 Trigger Docker image build with new version

## 7. Infrastructure Updates (lablink-template repo)
- [ ] 7.1 Update Terraform DNS logic
  - [ ] Remove pattern-based subdomain construction
  - [ ] Use single `dns.domain` value directly
  - [ ] Update Route53 record creation
- [ ] 7.2 Update Terraform SSL/Caddy logic
  - [ ] Handle new ssl.provider values
  - [ ] Conditional Caddy installation based on provider
  - [ ] Pass ALLOCATOR_FQDN as environment variable
- [ ] 7.3 Add Terraform ACM/ALB support
  - [ ] Conditional ALB creation when ssl.provider="acm"
  - [ ] ACM certificate attachment to ALB
  - [ ] ALB target group pointing to allocator EC2
  - [ ] Security group updates for ALB
- [ ] 7.4 Update example configs
  - [ ] Update dev/test/ci-test/prod configs
  - [ ] Add ACM example config
  - [ ] Remove deprecated fields
- [ ] 7.5 Add CI validation workflow
  - [ ] Install lablink-allocator package
  - [ ] Run lablink-validate-config on PRs modifying config
  - [ ] Block merge if validation fails

## 8. Testing and Validation (lablink-template repo)
- [ ] 8.1 Test deployment with each use case
  - [ ] IP-only (no DNS, no SSL)
  - [ ] CloudFlare DNS + SSL
  - [ ] Route53 + Let's Encrypt
  - [ ] Route53 + ACM (if ACM cert available)
  - [ ] Route53 manual DNS + Let's Encrypt
- [ ] 8.2 Verify subdomain takeover fix
  - [ ] Confirm sub-subdomains rejected at validation
  - [ ] Test that old configs fail validation with clear errors
- [ ] 8.3 Verify FQDN environment variable works
  - [ ] Check allocator logs show correct URL source
  - [ ] Verify clients connect successfully

## 9. Documentation and Release (lablink-template repo)
- [ ] 9.1 Update README with breaking changes notice
- [ ] 9.2 Create migration guide in docs
  - [ ] Step-by-step config conversion
  - [ ] Link to lablink repo migration guide
- [ ] 9.3 Update example deployment instructions
  - [ ] New config structure in quick start
  - [ ] ACM setup guide
- [ ] 9.4 Create GitHub release with migration notes
- [ ] 9.5 Notify users via GitHub discussions/issues