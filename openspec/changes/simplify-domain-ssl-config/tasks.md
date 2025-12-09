# Implementation Tasks

## 1. Configuration Schema Updates (lablink repo)
- [x] 1.1 Update `DNSConfig` dataclass in `structured_config.py`
  - [x] Remove: `app_name`, `pattern`, `custom_subdomain`, `create_zone`
  - [x] Keep: `enabled`, `terraform_managed`, `domain`, `zone_id`
  - [x] Update docstrings with new behavior
- [x] 1.2 Update `SSLConfig` dataclass in `structured_config.py`
  - [x] Change `provider` enum: `"none"`, `"letsencrypt"`, `"cloudflare"`, `"acm"`
  - [x] Remove: `staging` field
  - [x] Add: `certificate_arn` field (optional, for ACM)
  - [x] Update docstrings
- [x] 1.3 Update example `config.yaml` with new schema
  - [x] Use single `domain` field
  - [x] Remove deprecated fields
  - [x] Add comments explaining new structure

## 2. Validation Logic Enhancement (lablink repo)
- [x] 2.1 Create domain validator function
  - [x] Validate domain format (allows sub-subdomains)
  - [x] Reject domains starting/ending with dots
  - [x] Allow multi-level subdomains (e.g., `test.lablink.sleap.ai`)
- [x] 2.2 Enhance `validate_config.py` with new rules
  - [x] SSL non-"none" requires DNS enabled
  - [x] DNS enabled requires non-empty domain
  - [x] CloudFlare SSL requires terraform_managed=false
  - [x] Let's Encrypt requires valid email
  - [x] ACM requires certificate_arn when provider="acm"
  - [x] Domain format validation (leading/trailing dots)
- [x] 2.3 Add validation hook in `get_config.py`
  - [x] Call validators after config load
  - [x] Provide clear error messages on validation failure

## 3. Allocator FQDN Support (lablink repo)
- [x] 3.1 Update `config_helpers.py` to read `ALLOCATOR_FQDN` environment variable
  - [x] Priority: ALLOCATOR_FQDN > DNS config > IP fallback
  - [x] Log which URL source is being used
- [x] 3.2 Update URL construction logic
  - [x] Remove pattern-based concatenation
  - [x] Use simple domain from config or FQDN from env
- [x] 3.3 Update client connection logic
  - [x] Ensure clients can reach allocator via FQDN
  - [x] Update logging for debugging connection issues

## 4. Testing (lablink repo)
- [x] 4.1 Unit tests for domain validator
  - [x] Valid single and multi-level subdomains pass
  - [x] Sub-subdomains allowed (updated from proposal)
  - [x] Edge cases (no dots, trailing dots, leading dots)
- [x] 4.2 Unit tests for enhanced validation
  - [x] Test all five canonical use cases validate correctly
  - [x] Test invalid combinations rejected
  - [x] Test error messages are clear
- [x] 4.3 Integration tests for FQDN environment variable
  - [x] Test FQDN takes precedence over config
  - [x] Test fallback to config domain
  - [x] Test fallback to IP-only mode
- [x] 4.4 Update existing tests for schema changes
  - [x] Update test configs to new schema
  - [x] Remove tests for deprecated fields

## 5. Documentation (lablink repo)
- [ ] 5.1 Update CLAUDE.md with new configuration structure (future work)
- [ ] 5.2 Create migration guide document (future work)
  - [ ] Old schema → new schema mapping
  - [ ] Examples for each use case
  - [ ] Common migration scenarios
- [ ] 5.3 Update docs/ with new configuration guide (future work)
  - [ ] Document all five use cases
  - [ ] Add ACM setup instructions
  - [ ] Add troubleshooting section

## 6. Package Release (lablink repo)
- [ ] 6.1 Bump allocator package version (breaking change) (future work)
  - [ ] Update `pyproject.toml` version
  - [ ] Update CHANGELOG.md
- [ ] 6.2 Test package build locally (future work)
  - [ ] Build with `uv build`
  - [ ] Test installation from built package
- [ ] 6.3 Create git tag and push (future work)
- [ ] 6.4 Publish to PyPI via workflow (future work)
- [ ] 6.5 Trigger Docker image build with new version (future work)

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