# Proposal: Refactor CLAUDE.md to Follow OpenSpec Best Practices

## Why

The current `CLAUDE.md` (713 lines) duplicates most of `openspec/project.md` (250 lines) and contains detailed implementation documentation that belongs in specs or the documentation site. This violates OpenSpec best practices:

1. **Duplication**: ~80% of CLAUDE.md content is duplicated in project.md
2. **Maintenance burden**: Updates must be made in multiple places
3. **Confusion**: Inconsistencies can arise between the two files
4. **Wrong location**: Detailed API docs, database schemas, CI/CD workflows belong in specs

## What Changes

### Remove from CLAUDE.md (move to OpenSpec specs or docs site)
- Technology Stack details (already in project.md)
- Key Concepts (already in project.md)
- Configuration System details (already in project.md)
- Docker Strategy details → new `openspec/specs/docker/` spec
- CI/CD Workflows details → new `openspec/specs/ci-cd/` spec
- Database Schema → new `openspec/specs/database/` spec
- API Endpoints → new `openspec/specs/api/` spec
- Common Tasks (how-to guides) → docs site or slash commands
- Code Style Guidelines (already in project.md)
- Testing Strategy (already in project.md)
- Package Release Process → CI/CD spec
- Troubleshooting → docs site
- Documentation System → docs site

### Keep in CLAUDE.md (Claude-specific operational guidance)
- OpenSpec instructions block (auto-managed)
- Brief project overview (1-2 paragraphs)
- Repository structure (concise version)
- Slash commands reference table
- Notes for Claude section (behavioral guidance)
- Quick links to key resources

### New OpenSpec Specs to Create
1. **`openspec/specs/api/`** - API endpoints, request/response formats
2. **`openspec/specs/database/`** - Schema, triggers, migrations
3. **`openspec/specs/docker/`** - Image strategy, build process, venv setup
4. **`openspec/specs/ci-cd/`** - Workflows, release process, versioning

## Impact

### Affected Files
- **CLAUDE.md**: Reduced from ~713 lines to ~100 lines
- **openspec/project.md**: No changes (already correct)
- **New specs**: 4 new capability specs

### Benefits
- **Single source of truth**: No more duplication
- **Easier maintenance**: Update in one place
- **Better organization**: Specs organized by capability
- **OpenSpec compliance**: Follows best practices
- **Faster context loading**: Smaller CLAUDE.md = faster for AI assistants

### Non-Breaking
This is purely a documentation reorganization with no code changes.