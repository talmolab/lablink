# Infrastructure Repository Migration Plan

> **STATUS UPDATE (October 2025)**: Migration to separate repository is **ON HOLD**.
> The team has decided to keep everything in a **monorepo structure** for now.
> Infrastructure code remains in `lablink-infrastructure/` directory within the main repository.
> This document is kept for historical reference and future consideration.

**Original Goal**: Separate infrastructure deployment code into a standalone repository for easier management and clearer separation of concerns.

**Target Repository**: `talmolab/lablink-infrastructure` (to be created - POSTPONED)

**Current Status**: Infrastructure code exists in `lablink-infrastructure/` directory within main repository - **STAYING IN MONOREPO**

## Migration Overview

### What Will Move
- `/lablink-infrastructure/` → Entire directory to new repo root
- Terraform configurations
- Deployment scripts
- Configuration templates
- Documentation specific to infrastructure

### What Will Stay
- `/packages/` → Python packages remain in main repo
- `/lablink-client-base/` → Client Docker images
- `/lablink-allocator/` → Old structure (deprecated but kept for reference)
- `/docs/` → Main documentation (with links updated)
- `/tests/` → Package tests

## Current State Analysis

### Repository Structure
```
lablink/
├── lablink-infrastructure/      # → MOVE TO NEW REPO
│   ├── main.tf
│   ├── backend.tf
│   ├── variables.tf
│   ├── outputs.tf
│   ├── user_data.sh
│   ├── config/
│   │   └── config.yaml
│   ├── verify-deployment.sh
│   └── README-VERIFY.md
├── packages/                     # KEEP
│   ├── allocator/
│   └── client/
├── lablink-client-base/         # KEEP
├── lablink-allocator/           # KEEP (deprecated)
├── docs/                        # KEEP (update links)
└── .github/workflows/           # SPLIT: some move, some stay
```

### GitHub Actions Workflows

**Move to new repo**:
- `lablink-allocator-terraform.yml` → Infrastructure deployment
- `lablink-allocator-destroy.yml` → Infrastructure teardown
- `client-vm-infrastructure-test.yml` → E2E infrastructure tests

**Keep in main repo**:
- `ci.yml` → Python package testing
- `docs.yml` → Documentation deployment
- `lablink-images.yml` → Docker image building

## Migration Steps

### Phase 1: Preparation (Current)
- [x] Create VM_REGISTRATION_ISSUE.md documenting current bug
- [x] Create DNS configuration documentation
- [x] Update troubleshooting guide with DNS and VM issues
- [x] Review and test all infrastructure deployment paths
- [x] Fix HTTPS support for client services (VM registration, GPU health, status updates)
- [x] Update DNS verification workflow to use curl instead of dig
- [x] Test Chrome Remote Desktop workflow with HTTPS allocator
- [ ] Document all environment variables and secrets
- [ ] List all GitHub repository settings/secrets needed

### Phase 2: Repository Setup
- [ ] Create `talmolab/lablink-infrastructure` repository
- [ ] Set up branch protection rules
- [ ] Configure GitHub Actions secrets:
  - AWS_REGION
  - AWS_ACCOUNT_ID
  - GITHUB_TOKEN (automatic)
- [ ] Set up OIDC provider for AWS authentication
- [ ] Create IAM role for GitHub Actions

### Phase 3: Code Migration
- [ ] Copy `lablink-infrastructure/` to new repo root
- [ ] Move relevant workflows to new repo `.github/workflows/`
- [ ] Update terraform backend configurations
- [ ] Create new repo README.md
- [ ] Set up issue/PR templates
- [ ] Configure branch protection

### Phase 4: Documentation Updates
- [ ] Update main repo docs with links to infrastructure repo
- [ ] Move infrastructure-specific docs to new repo
- [ ] Update CLAUDE.md with new repo structure
- [ ] Create migration guide for users
- [ ] Update quickstart guide with new paths

### Phase 5: Testing
- [ ] Test infrastructure deployment from new repo
- [ ] Verify GitHub Actions workflows
- [ ] Test destroy workflow
- [ ] Run E2E tests
- [ ] Verify documentation links

### Phase 6: Cleanup
- [ ] Archive `lablink-infrastructure/` in main repo
- [ ] Remove migrated workflows from main repo
- [ ] Update main repo README
- [ ] Create redirect/deprecation notices
- [ ] Tag release in both repos

### Phase 7: Communication
- [ ] Announce migration to users
- [ ] Update external documentation
- [ ] Create migration FAQ
- [ ] Update deployment guides

## Files to Migrate

### Infrastructure Code
```
lablink-infrastructure/
├── main.tf                  # Core infrastructure
├── backend.tf               # Terraform state backend
├── variables.tf             # Input variables
├── outputs.tf               # Output values
├── user_data.sh             # EC2 initialization script
├── config/
│   ├── config.yaml          # Main configuration
│   └── config-template.yaml # Template for users
├── verify-deployment.sh     # Deployment verification
└── README-VERIFY.md         # Verification documentation
```

### GitHub Actions
```
.github/workflows/
├── lablink-allocator-terraform.yml  # Deploy infrastructure
├── lablink-allocator-destroy.yml    # Destroy infrastructure
└── client-vm-infrastructure-test.yml # E2E tests
```

### Documentation
```
docs/
├── dns-configuration.md     # DNS setup (move)
├── deployment.md            # Update with new repo links
└── troubleshooting.md       # Update with new repo links
```

## Configuration Changes

### Terraform Backend
Current backends reference main repo:
```hcl
# backend-test.hcl
bucket = "tf-state-lablink-allocator-bucket"
key    = "lablink-allocator/test/terraform.tfstate"
```

New backends will reference infrastructure repo:
```hcl
# backend-test.hcl
bucket = "tf-state-lablink-infrastructure-bucket"
key    = "lablink-infrastructure/test/terraform.tfstate"
```

### GitHub Actions Secrets
**Required in new repo**:
- AWS_REGION (environment variable)
- AWS_ACCOUNT_ID (for OIDC)
- No stored credentials (use OIDC)

**IAM Role Setup**:
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "arn:aws:iam::{account-id}:oidc-provider/token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:talmolab/lablink-infrastructure:*"
      }
    }
  }]
}
```

## Package Dependencies

### Python Packages
Infrastructure repo will depend on published packages from main repo:
- `lablink-allocator` → Published to PyPI/GitHub Packages
- `lablink-client-service` → Published to PyPI/GitHub Packages

### Docker Images
Infrastructure will reference images from main repo:
- `ghcr.io/talmolab/lablink-allocator:version`
- `ghcr.io/talmolab/lablink-client-base-image:version`

**Image versioning strategy**:
- Use semantic versions for production: `v1.0.0`
- Use branch tags for testing: `linux-amd64-test`
- Pin specific versions in production configs

## Known Issues to Address Before Migration

### Critical Bugs
1. ~~**VM Registration Issue**~~ - ✅ **FIXED**
   - ~~`/api/launch` doesn't insert VMs into database~~
   - Fixed: HTTPS support added to all client services
   - Client VMs now use `ALLOCATOR_URL` environment variable for HTTPS
   - Deployed and tested successfully

2. **DNS Zone ID Hardcoding**
   - Currently requires hardcoded zone_id in config
   - Consider making zone lookup more robust
   - Document clearly in new repo

3. **DNS Verification Workflow** - ✅ **FIXED**
   - ~~Old workflow used `dig` which failed with Cloudflare DNS~~
   - Updated to use `curl` for HTTPS connectivity check
   - More reliable for proxied domains

### Configuration Management
1. **Config Schema Validation**
   - Add validation for config.yaml
   - Prevent missing required fields
   - Better error messages

2. **Environment-Specific Configs**
   - Create templates for dev/test/prod
   - Document all configuration options
   - Add config validation script

## Post-Migration Workflow

### Deployment Process (After Migration)

**1. Update Infrastructure**:
```bash
# Clone infrastructure repo
git clone https://github.com/talmolab/lablink-infrastructure
cd lablink-infrastructure

# Edit configuration
vim config/config.yaml

# Deploy
terraform init
terraform apply
```

**2. Update Packages** (if needed):
```bash
# In main lablink repo
cd packages/allocator
# Make changes
git commit && git push

# GitHub Actions builds and publishes new version
# Wait for package publish

# Update infrastructure config to use new version
cd lablink-infrastructure
vim config/config.yaml  # Update package version
terraform apply
```

### Version Pinning Strategy

**Production**:
```yaml
machine:
  image: "ghcr.io/talmolab/lablink-allocator:v1.2.3"
  repository: "https://github.com/talmolab/lablink"
```

**Testing**:
```yaml
machine:
  image: "ghcr.io/talmolab/lablink-allocator:linux-amd64-test"
  repository: "https://github.com/talmolab/lablink"
```

## Risk Assessment

### High Risk
- **State file migration** - Terraform state must be preserved
  - Mitigation: Backup state files before migration
  - Test migration in non-production first

- **Broken dependencies** - Infrastructure depends on packages/images
  - Mitigation: Pin versions explicitly
  - Test with current versions before migration

### Medium Risk
- **Documentation links** - Many docs reference current structure
  - Mitigation: Update all links systematically
  - Add redirects where possible

- **User confusion** - Two repos instead of one
  - Mitigation: Clear migration guide
  - Update all external documentation

### Low Risk
- **CI/CD workflows** - May need debugging in new repo
  - Mitigation: Test thoroughly before announcing
  - Keep old workflows temporarily

## Testing Checklist

Before declaring migration complete:

- [ ] Fresh deployment works from new repo
- [ ] Existing deployment can be updated
- [ ] Destroy workflow works
- [ ] DNS configuration works
- [ ] SSL certificates obtain successfully
- [ ] Client VMs register (after bug fix)
- [ ] All documentation links work
- [ ] GitHub Actions run successfully
- [ ] Terraform state is accessible
- [ ] Rollback procedure tested

## Rollback Plan

If migration causes issues:

1. **Keep old structure temporarily**:
   - Don't delete `lablink-infrastructure/` from main repo immediately
   - Keep old workflows disabled but present

2. **State file access**:
   - Ensure S3 buckets accessible from both repos
   - Document how to point terraform at old state

3. **Documentation**:
   - Keep old documentation accessible
   - Add notes about where to find current info

## Timeline

**Estimated Duration**: 2-3 weeks

**Week 1**: Preparation and Setup
- Fix VM registration bug
- Review and document everything
- Create new repository
- Set up AWS resources

**Week 2**: Migration and Testing
- Copy code to new repo
- Update workflows and docs
- Test all deployment scenarios
- Fix issues found during testing

**Week 3**: Finalization and Communication
- Final testing
- Update all documentation
- Announce migration
- Monitor for issues

## Success Criteria

Migration is successful when:
- ✅ Infrastructure can be deployed from new repo
- ✅ All GitHub Actions workflows pass
- ✅ Documentation is complete and accurate
- ✅ No regressions in functionality
- ✅ Users can follow migration guide successfully
- ✅ Old repo clearly indicates where to find new code

## Open Questions

1. **Package Publishing**: Should infrastructure repo trigger package builds in main repo?
   - Option A: Keep separate (infrastructure uses published versions)
   - Option B: Add workflow to trigger builds
   - **Recommendation**: Keep separate for cleaner separation

2. **Version Coordination**: How to ensure infrastructure uses compatible package versions?
   - Option A: Manual version updates in config
   - Option B: Automated compatibility checking
   - **Recommendation**: Start with manual, add automation later

3. **Documentation Split**: Where should each doc live?
   - Main repo: Package development, API docs, contributing
   - Infrastructure repo: Deployment, DNS, AWS setup
   - **Recommendation**: Document in both with cross-links

4. **State File Location**: Keep current S3 bucket or create new one?
   - Current: `tf-state-lablink-allocator-bucket`
   - **Recommendation**: Create new bucket for infrastructure repo

## Resources

- [Terraform State Migration Guide](https://www.terraform.io/docs/language/state/remote-state-data.html)
- [GitHub OIDC with AWS](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)
- [Repository Migration Best Practices](https://docs.github.com/en/github/administering-a-repository)

## Recent Progress (October 2025)

### HTTPS Support Implementation ✅
- **Problem**: Client VMs couldn't communicate with HTTPS allocator
- **Solution**:
  - Added `ALLOCATOR_URL` environment variable support to all client services
  - Updated subscribe.py, check_gpu.py, update_inuse_status.py
  - Implemented timeout tuples for better error handling
  - Added retry logic with 60s delays for transient failures
- **Files Changed**:
  - `packages/client/src/lablink_client/subscribe.py`
  - `packages/client/src/lablink_client/check_gpu.py`
  - `packages/client/src/lablink_client/update_inuse_status.py`
  - `packages/client/tests/test_subscribe.py`
  - `packages/client/tests/test_check_gpu.py`

### DNS Verification Fix ✅
- **Problem**: GitHub Actions DNS check using `dig` failed with Cloudflare
- **Solution**: Changed to `curl` for HTTPS connectivity check
- **File Changed**: `.github/workflows/lablink-allocator-terraform.yml`

## Next Actions

**Immediate** (Before Migration):
1. ~~Fix VM registration bug~~ ✅ COMPLETED
2. ~~Test fix in current setup~~ ✅ COMPLETED
3. Test client VM launch and Chrome Remote Desktop connection ⏳ IN PROGRESS
4. Document all environment variables and secrets
5. Create infrastructure repo

**Short Term** (During Migration):
1. Copy infrastructure code
2. Set up GitHub Actions
3. Test deployment pipeline
4. Update documentation

**Long Term** (After Migration):
1. Deprecate old structure
2. Monitor for issues
3. Improve infrastructure code
4. Add more automation
