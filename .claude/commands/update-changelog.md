# Update CHANGELOG

Maintain the project CHANGELOG.md following Keep a Changelog format.

## Command Template

```
Update CHANGELOG.md based on recent changes. Review git commits since last release and categorize changes.
```

## CHANGELOG Format

The project follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) format:

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- New features that have been added

### Changed
- Changes to existing functionality

### Fixed
- Bug fixes

### Deprecated
- Features that will be removed in future versions

### Removed
- Features that have been removed

### Security
- Security fixes and improvements

## [0.0.2a0] - 2025-01-15

### Added
- Initial release features
```

## When to Update CHANGELOG

Update CHANGELOG when:
- Adding new features
- Fixing bugs
- Making breaking changes
- Updating dependencies (if significant)
- Improving documentation (if substantial)
- Refactoring code (if affects users)

## Manual Update Process

### Step 1: Review Recent Changes

```bash
# View commits since last tag
git log --oneline $(git describe --tags --abbrev=0)..HEAD

# Or view commits since specific date
git log --oneline --since="2025-01-01"

# Or view diff since last tag
git diff $(git describe --tags --abbrev=0)..HEAD --stat
```

### Step 2: Categorize Changes

**Added** - New features:
- New API endpoints or capabilities
- New configuration options
- New Docker image features
- New documentation sections

**Changed** - Modifications to existing features:
- Updated behavior
- Improved performance
- Enhanced error messages
- Configuration changes

**Fixed** - Bug fixes:
- Corrected errors
- Fixed crashes or failures
- Resolved edge cases
- Database or Terraform fixes

**Deprecated** - Soon to be removed:
- Features marked for future removal
- Old configuration options being replaced

**Removed** - Deleted features:
- Removed endpoints or functions
- Deleted deprecated code

**Security** - Security improvements:
- Vulnerability fixes
- Input validation improvements
- Authentication/authorization updates

### Step 3: Write Entry

```markdown
## [Unreleased]

### Added
- Claude development commands for streamlined workflows (`/test-allocator`, `/docker-build`, etc.)
- HTTPS support for client services with `ALLOCATOR_URL` environment variable
- Comprehensive Docker container verification tests
- OpenSpec change proposal workflow and documentation

### Changed
- Improved database connection handling with better error messages
- Enhanced Docker build process with explicit venv paths
- Updated Python version requirement documentation for both packages
- Migrated allocator infrastructure deployment to lablink-template repository

### Fixed
- Corrected venv activation in Docker containers
- Fixed Terraform validation errors in client VM creation
- Resolved import errors in production Docker images
- Fixed coverage reporting for monorepo packages

### Security
- Added input validation for file path parameters
- Improved error handling to prevent information leakage in logs
- Updated default password recommendations in documentation
```

## Release Process

When ready to release a version:

### Step 1: Move Unreleased to Versioned

```markdown
## [Unreleased]

(Leave empty or add future planned items)

## [0.0.2a0] - 2025-01-15

### Added
- (move items from Unreleased here)

### Changed
- (move items from Unreleased here)

### Fixed
- (move items from Unreleased here)
```

### Step 2: Update Version

Follow [Semantic Versioning](https://semver.org/):

- **MAJOR** (0.x.x -> 1.0.0): Breaking changes
- **MINOR** (0.1.x -> 0.2.0): New features (backward compatible)
- **PATCH** (0.0.x -> 0.0.y): Bug fixes (backward compatible)

### Step 3: Create Git Tag

```bash
# Tag the allocator release
git tag -a lablink-allocator-service_v0.0.2a0 -m "Release allocator 0.0.2a0"

# Tag the client release
git tag -a lablink-client-service_v0.0.7a0 -m "Release client 0.0.7a0"

# Push tags
git push origin --tags
```

## Best Practices

### Be User-Focused

```markdown
Good: "Added automatic retry for failed VM allocations with exponential backoff"
Bad:  "Refactored retry logic implementation"

Good: "Fixed allocator crash when PostgreSQL connection times out"
Bad:  "Fixed database bug"
```

### Include Context

```markdown
Good: "Updated Flask to 3.0.0 for security fixes (CVE-2024-XXXX)"
Bad:  "Updated Flask"

Good: "Deprecated `--legacy-config` flag; will be removed in v1.0.0 (use Hydra config instead)"
Bad:  "Deprecated --legacy-config"
```

### Reference PRs and Issues

```markdown
### Added
- Claude development commands for improved workflows (#42)
- HTTPS support for client services (#38)

### Fixed
- Corrected database connection handling (fixes #35)
- Resolved Docker build failures on Windows (#40)
```

### Group Related Changes

```markdown
### Changed
- Docker improvements:
  - Multi-stage builds for smaller image size
  - Explicit venv paths for reliability
  - Build verification in CI workflow
```

## Quick Commands

```bash
# View commits for CHANGELOG entry
git log --oneline --no-merges v0.0.1a0..HEAD

# Count commits by type (conventional commits)
git log --oneline v0.0.1a0..HEAD | grep -c "^[a-f0-9]* feat:"
git log --oneline v0.0.1a0..HEAD | grep -c "^[a-f0-9]* fix:"

# Generate commit list
git log --pretty=format:"- %s (%h)" v0.0.1a0..HEAD
```

## CHANGELOG Location

- **File**: `CHANGELOG.md` (project root)
- **Format**: Markdown
- **Sections**: Sorted by version (newest first)

## Verification

After updating:

```bash
# Check markdown syntax with ruff (if configured)
# Verify version numbers follow semver
# Check dates are in YYYY-MM-DD format
# Ensure each entry is actionable and user-focused
```

## Related Commands

- `/pr-description` - Generate PR descriptions (source for CHANGELOG entries)
- `/review-pr` - Review PRs (may identify CHANGELOG-worthy changes)