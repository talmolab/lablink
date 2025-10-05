# Infrastructure Repository Migration Plan

> **STATUS UPDATE (October 2025)**: Migration to separate repository is **ACTIVE**.
> The infrastructure code will be moved to `lablink-template` as a template repository.
> This document tracks the migration progress and strategy.

**Goal**: Separate infrastructure deployment code into a template repository that users can clone and customize for their own LabLink deployments.

**Target Repository**: `talmolab/lablink-template` (to be created)

**Example Deployment**: `talmolab/sleap-lablink` (SLEAP-specific deployment from template)

## Migration Strategy

### What Will Move to `lablink-template`

**Infrastructure code:**
- `/lablink-infrastructure/` → Template repository root
- Terraform configurations (`main.tf`, `variables.tf`, `outputs.tf`, etc.)
- Configuration files (`config/config.yaml`)
- User data scripts
- Deployment verification scripts

**GitHub Actions workflows:**
- `lablink-allocator-terraform.yml` → Infrastructure deployment
- `lablink-allocator-destroy.yml` → Infrastructure teardown
- `client-vm-infrastructure-test.yml` → E2E testing (optional)

**Documentation:**
- Deployment guide
- Configuration guide
- DNS setup
- AWS setup
- Troubleshooting specific to deployment

### What Will Stay in Main Repo (`talmolab/lablink`)

**Python packages:**
- `/packages/allocator/` → Allocator service package
- `/packages/client/` → Client service package

**Documentation:**
- `/docs/` → Package development docs, API reference, contributing guides
- Links will be added to template repo where appropriate

**GitHub Actions workflows:**
- `ci.yml` → Python package testing and linting
- `docs.yml` → Documentation deployment to GitHub Pages
- `lablink-images.yml` → Docker image building and publishing
- `publish-packages.yml` → Python package publishing to PyPI

### What Will Be Removed

**Deprecated old structure:**
- `/lablink-allocator/` → Old allocator structure (superseded by `/packages/allocator/`)
- `/lablink-client-base/` → Old client structure (superseded by `/packages/client/`)

## Template Repository Structure

```
lablink-template/
├── main.tf                          # Core infrastructure
├── variables.tf                     # Input variables
├── outputs.tf                       # Output values
├── backend.tf                       # Terraform backend config
├── backend-dev.hcl                  # Dev backend
├── backend-test.hcl                 # Test backend
├── backend-prod.hcl                 # Prod backend
├── user_data.sh                     # EC2 initialization
├── config/
│   ├── config.yaml                  # Configuration file
│   └── config-template.yaml         # Template with comments
├── .github/
│   └── workflows/
│       ├── deploy.yml               # Deploy infrastructure
│       ├── destroy.yml              # Destroy infrastructure
│       └── test.yml                 # E2E testing (optional)
├── scripts/
│   ├── verify-deployment.sh         # Deployment verification
│   └── setup-secrets.sh             # GitHub secrets setup helper
├── docs/
│   ├── README.md                    # Main documentation
│   ├── deployment.md                # Deployment guide
│   ├── configuration.md             # Configuration reference
│   ├── dns-setup.md                 # DNS configuration
│   ├── aws-setup.md                 # AWS prerequisites
│   └── troubleshooting.md           # Common issues
├── .gitignore
├── LICENSE
└── README.md                        # Template README
```

## Example: SLEAP Deployment

Once the template is working, we'll create `talmolab/sleap-lablink` from it:

```
sleap-lablink/ (created from lablink-template)
├── [Same structure as template]
├── config/
│   └── config.yaml                  # SLEAP-specific configuration
│       machine:
│         image: "ghcr.io/talmolab/lablink-client-base-image:latest"
│         repository: "https://github.com/talmolab/sleap-tutorial-data.git"
│         software: "sleap"
└── README.md                        # SLEAP deployment documentation
```

## Required Configuration & Environment Variables

### GitHub Repository Secrets

**Required for GitHub Actions:**
- None (uses OIDC for AWS authentication)

**Optional (can override defaults):**
- `ADMIN_PASSWORD` → Override admin password
- `DB_PASSWORD` → Override database password

### GitHub Repository Variables

**Required:**
- None (configured in `config/config.yaml`)

### AWS Prerequisites

**IAM Role for OIDC:**
- Role ARN with trust policy for GitHub Actions
- Permissions: EC2, VPC, S3, Route53 (if using DNS)

**S3 Bucket:**
- Terraform state storage
- Bucket name specified in `backend-*.hcl` files

**Route 53 (optional):**
- Hosted zone for DNS management
- Zone ID in configuration

### Configuration File (`config/config.yaml`)

**Required settings:**
```yaml
db:
  password: "CHANGE_ME"              # Database password

machine:
  ami_id: "ami-..."                  # Region-specific AMI
  image: "ghcr.io/..."               # Docker image
  repository: "https://github.com/..." # Optional: code repository

app:
  admin_password: "CHANGE_ME"        # Admin UI password
  region: "us-west-2"                # AWS region

bucket_name: "tf-state-your-deployment" # S3 bucket name

dns:
  enabled: true/false                # DNS management
  zone_id: "Z..."                    # Route 53 zone (if enabled)
  domain: "your-domain.com"          # Domain name

ssl:
  provider: "letsencrypt"/"none"     # SSL certificate provider
  email: "admin@example.com"         # For Let's Encrypt
```

## Migration Steps

### Phase 1: Preparation ✅ COMPLETED
- [x] Fix VM registration bug (HTTPS support)
- [x] Update documentation structure
- [x] Standardize Dockerfiles and virtual environments
- [x] Update AMI configurations
- [x] Format Terraform files
- [x] Test current deployment workflow

### Phase 2: Template Repository Creation 🔄 IN PROGRESS
- [ ] Create `talmolab/lablink-template` repository
- [ ] Mark as template repository in GitHub settings
- [ ] Set up branch protection rules
- [ ] Configure OIDC for AWS (document IAM role ARN pattern)
- [ ] Copy `lablink-infrastructure/` contents to template root
- [ ] Move deployment workflows to template
- [ ] Create comprehensive README for template users
- [ ] Add configuration examples and templates
- [ ] Document all required secrets and variables

### Phase 3: Template Documentation
- [ ] Write deployment guide for template users
- [ ] Document AWS setup requirements
- [ ] Create DNS configuration guide
- [ ] Write SSL/TLS setup guide
- [ ] Create troubleshooting guide
- [ ] Add quickstart guide
- [ ] Document environment-specific configs (dev/test/prod)

### Phase 4: Main Repo Cleanup
- [ ] Remove `/lablink-allocator/` directory
- [ ] Remove `/lablink-client-base/` directory
- [ ] Remove infrastructure workflows from main repo
- [ ] Update main repo README to point to template
- [ ] Update docs with links to template repo
- [ ] Add migration guide for existing users

### Phase 5: SLEAP Deployment
- [ ] Create `talmolab/sleap-lablink` from template
- [ ] Configure for SLEAP-specific settings
- [ ] Set up DNS (lablink.sleap.ai or similar)
- [ ] Deploy and test
- [ ] Document SLEAP-specific configuration
- [ ] Use as reference implementation

### Phase 6: Testing & Validation
- [ ] Test fresh deployment from template
- [ ] Test with different AWS regions
- [ ] Test with and without DNS
- [ ] Test with different Docker images
- [ ] Verify all documentation is accurate
- [ ] Test SLEAP deployment end-to-end

### Phase 7: Announcement
- [ ] Create migration guide for existing deployments
- [ ] Announce template repository
- [ ] Update external links and documentation
- [ ] Create video/written tutorial for template usage

## Package Dependencies

### Docker Images (Published from Main Repo)
Template deployments will use Docker images built and published from `talmolab/lablink`:
- `ghcr.io/talmolab/lablink-allocator-image:version`
- `ghcr.io/talmolab/lablink-client-base-image:version`

**Versioning strategy:**
- Production deployments: Pin to specific version (e.g., `v1.0.0`)
- Testing deployments: Use branch tags (e.g., `linux-amd64-test`)
- Latest stable: Use `latest` tag

### Python Packages (Published to PyPI)
Docker images install packages from PyPI:
- `lablink-allocator-service`
- `lablink-client-service`

## Template Usage Workflow

### For Template Users

**1. Create deployment from template:**
```bash
# On GitHub: Use "Use this template" button
# Or via CLI:
gh repo create my-org/my-lablink-deployment --template talmolab/lablink-template
cd my-lablink-deployment
```

**2. Configure deployment:**
```bash
# Edit configuration
cp config/config-template.yaml config/config.yaml
vim config/config.yaml

# Update passwords, AMI IDs, domain, etc.
```

**3. Set up AWS:**
```bash
# Create S3 bucket for state
aws s3 mb s3://tf-state-my-deployment

# Create IAM role for GitHub Actions (see docs/aws-setup.md)
```

**4. Deploy:**
```bash
# Via GitHub Actions (recommended)
# Go to Actions → Deploy → Run workflow

# Or locally:
terraform init -backend-config=backend-prod.hcl
terraform apply
```

### For Main Repo Developers

**1. Update packages:**
```bash
cd lablink/packages/allocator
# Make changes
git commit && git push

# CI builds and publishes new version
```

**2. Update Docker images:**
```bash
# Triggered automatically by package publish
# Or manually via GitHub Actions
```

**3. Template users update their deployments:**
```bash
# In their deployment repo
vim config/config.yaml  # Update image tag
terraform apply
```

## Known Issues & Solutions

### Issue: VM Registration with HTTPS ✅ FIXED
- **Solution**: HTTPS support added to all client services
- **Status**: Resolved, deployed, tested

### Issue: DNS Verification ✅ FIXED
- **Solution**: Changed from `dig` to `curl` for verification
- **Status**: Resolved

### Issue: Terraform State Management
- **Challenge**: Each deployment needs separate state
- **Solution**: Template includes backend config examples
- **Documentation**: Clear guide on S3 bucket setup

### Issue: AMI Region Specificity
- **Challenge**: AMI IDs are region-specific
- **Solution**: Document AMI lookup process
- **Future**: Consider automated AMI lookup by region

## Testing Checklist

Before declaring migration complete:

**Template Repository:**
- [ ] Fresh deployment works from template
- [ ] All workflows run successfully
- [ ] Documentation is complete and accurate
- [ ] Configuration validation works
- [ ] DNS setup works
- [ ] SSL certificates obtain successfully
- [ ] Client VMs register correctly

**SLEAP Deployment:**
- [ ] SLEAP-specific deployment works
- [ ] SLEAP tutorial data clones correctly
- [ ] Chrome Remote Desktop works
- [ ] All SLEAP workflows function

**Main Repository:**
- [ ] Package CI/CD still works
- [ ] Docker images still build
- [ ] Documentation builds successfully
- [ ] All links updated correctly

## Success Criteria

Migration is successful when:
- ✅ Template repository is functional and documented
- ✅ Users can create deployments from template
- ✅ SLEAP deployment works as reference implementation
- ✅ Main repo focuses solely on package development
- ✅ No functionality regressions
- ✅ Clear separation of concerns
- ✅ Documentation is comprehensive

## Timeline

**Estimated Duration**: 2-3 weeks

**Week 1**: Template Creation
- Create template repository
- Move infrastructure code
- Set up workflows
- Create initial documentation

**Week 2**: Testing & Documentation
- Test template deployment
- Complete documentation
- Create SLEAP deployment
- Fix issues found during testing

**Week 3**: Main Repo Cleanup & Launch
- Clean up main repository
- Update all documentation
- Announce template availability
- Monitor for issues

## Resources

- [GitHub Template Repositories](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-template-repository)
- [Terraform State Migration](https://www.terraform.io/docs/language/state/remote-state-data.html)
- [GitHub OIDC with AWS](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)

## Recent Progress (October 2025)

### Repository Restructure ✅
- Moved allocator to `packages/allocator/`
- Moved client to `packages/client/`
- Standardized Dockerfiles with explicit venv paths
- Updated all documentation

### HTTPS Support ✅
- Added ALLOCATOR_URL support to all client services
- Tested with production HTTPS deployment
- All services working correctly

### AMI Updates ✅
- Updated to Ubuntu 24.04 custom AMIs
- Client: ami-0601752c11b394251 (with Docker + Nvidia)
- Allocator: ami-0bd08c9d4aa9f0bc6 (with Docker)

## Next Steps

**Immediate:**
1. Create `lablink-template` repository
2. Copy infrastructure code
3. Write template README and documentation

**Short Term:**
4. Test template deployment
5. Create SLEAP deployment from template
6. Clean up main repository

**Long Term:**
7. Announce template availability
8. Support users creating deployments
9. Iterate based on feedback
