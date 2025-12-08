<!-- OPENSPEC:START -->
# OpenSpec Instructions

These instructions are for AI assistants working in this project.

Always open `@/openspec/AGENTS.md` when the request:
- Mentions planning or proposals (words like proposal, spec, change, plan)
- Introduces new capabilities, breaking changes, architecture shifts, or big performance/security work
- Sounds ambiguous and you need the authoritative spec before coding

Use `@/openspec/AGENTS.md` to learn:
- How to create and apply change proposals
- Spec format and conventions
- Project structure and guidelines

Keep this managed block so 'openspec update' can refresh the instructions.

<!-- OPENSPEC:END -->

# Claude Developer Guide

**LabLink** is a dynamic VM allocation and management system for computational research workflows. See `openspec/project.md` for full project context, conventions, and constraints.

## Key Resources

| Resource | Location |
|----------|----------|
| Project conventions | `openspec/project.md` |
| API endpoints | `openspec/specs/api/spec.md` |
| Database schema | `openspec/specs/database/spec.md` |
| Docker strategy | `openspec/specs/docker/spec.md` |
| CI/CD workflows | `openspec/specs/ci-cd/spec.md` |
| Documentation | https://talmolab.github.io/lablink/ |

## Repository Structure

```
lablink/
├── packages/
│   ├── allocator/          # Allocator service (Flask, Terraform)
│   └── client/             # Client service (GPU health, subscription)
├── openspec/
│   ├── project.md          # Project conventions
│   ├── specs/              # Capability specifications
│   └── changes/            # Change proposals
├── .claude/commands/       # Slash commands for development
└── docs/                   # MkDocs documentation
```

## Slash Commands

Use these commands for common development tasks:

| Category | Commands |
|----------|----------|
| **Testing** | `/test-allocator`, `/test-client`, `/test-coverage`, `/lint`, `/lint-fix` |
| **Docker** | `/docker-build-allocator`, `/docker-build-client`, `/docker-test-allocator`, `/docker-test-client` |
| **CI/CD** | `/trigger-ci`, `/trigger-docker-build`, `/publish-allocator`, `/publish-client` |
| **Git & PR** | `/pr-description`, `/review-pr`, `/update-changelog` |
| **Docs** | `/docs-serve`, `/docs-build` |
| **Dev** | `/dev-setup`, `/run-allocator-local`, `/validate-terraform` |

See `.claude/commands/README.md` for full documentation.

## Quick Reference

```bash
# Run tests
cd packages/allocator && PYTHONPATH=. pytest
cd packages/client && PYTHONPATH=. pytest

# Lint
ruff check packages/allocator packages/client

# Build Docker (dev)
docker build -t lablink-allocator:dev -f packages/allocator/Dockerfile.dev .
```

## Notes for Claude

### When Making Changes
1. Read existing code before editing
2. Follow patterns in `openspec/project.md`
3. Add tests for new functionality
4. Update specs if behavior changes

### When Adding Features
1. Check if an OpenSpec proposal is needed (see `openspec/AGENTS.md`)
2. Add to structured config if user-facing
3. Document in appropriate spec

### Code Review Checklist
- [ ] Follows existing patterns
- [ ] Tests added/updated
- [ ] No secrets committed
- [ ] Backwards compatible (or documented)
