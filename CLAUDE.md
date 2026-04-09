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

**LabLink** is a cloud-based virtual teaching lab accessible through Chrome browser. It consists of three packages: an **allocator** service (Flask API that orchestrates VM provisioning), a **client** service (runs on GPU VMs for health reporting), and a **CLI** tool (Typer-based command-line interface for deploying and managing infrastructure). See `openspec/project.md` for full project context, conventions, and constraints.

## Key Resources

| Resource | Location |
|----------|----------|
| Project conventions | `openspec/project.md` |
| API endpoints | `openspec/specs/api/spec.md` |
| Database schema | `openspec/specs/database/spec.md` |
| Docker strategy | `openspec/specs/docker/spec.md` |
| CI/CD workflows | `openspec/specs/ci-cd/spec.md` |
| Configuration reference | `docs/configuration.md` |
| Configuration examples | `docs/configuration.md#full-configuration-examples` |
| Documentation site | https://talmolab.github.io/lablink/ |

## Repository Structure

```
lablink/
├── packages/
│   ├── allocator/          # Allocator service (Flask, Terraform)
│   ├── client/             # Client service (GPU health, subscription)
│   └── cli/                # CLI tool (Typer, deploys infrastructure)
│       └── src/lablink_cli/
│           ├── app.py              # CLI entry point and commands
│           ├── terraform_source.py # Downloads Terraform files from lablink-template releases
│           ├── commands/           # Command implementations (deploy, destroy, status, logs, etc.)
│           ├── config/             # Config schema and validation
│           └── tui/                # Interactive TUI (wizard, logs viewer)
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

### Workflows
Before implementing changes, present a plan and get user approval. Do not start coding until the approach is confirmed, especially for refactors or multi-file changes.

## Quick Reference

```bash
# Run tests
cd packages/allocator && PYTHONPATH=. pytest
cd packages/client && PYTHONPATH=. pytest
cd packages/cli && PYTHONPATH=src pytest  # integration tests: pytest -m integration

# Lint
ruff check packages/allocator packages/client packages/cli

# Build Docker (dev)
docker build -t lablink-allocator:dev -f packages/allocator/Dockerfile.dev .
```

## CLI Architecture

The CLI (`lablink` command) downloads Terraform files from tagged GitHub releases of `talmolab/lablink-template` instead of bundling copies. This keeps the template repo as the single source of truth.

- **Template version**: Pinned in `packages/cli/src/lablink_cli/__init__.py` (`TEMPLATE_VERSION`, `TEMPLATE_SHA256`)
- **Cache**: Downloaded templates are cached at `~/.lablink/cache/terraform/{version}/`
- **Override flags**: `--template-version v0.2.0` (custom version, skips checksum) and `--terraform-bundle ./file.tar.gz` (offline mode)
- **Region**: Passed as `-var=region=` to Terraform (not string-replaced in `.tf` files)
- **Template repo**: `talmolab/lablink-template` — allocator infrastructure Terraform configs

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

## Cross-Repo Dependencies

LabLink spans two repositories:
- **`talmolab/lablink`** (this repo): Python packages (allocator, client, CLI), CI/CD, docs
- **`talmolab/lablink-template`**: Terraform configs for allocator infrastructure deployment. The CLI downloads from tagged releases of this repo. Changes to Terraform (IAM policies, provider config, resource definitions) must be made in the template repo and released with a new tag. Then update `TEMPLATE_VERSION` and `TEMPLATE_SHA256` in the CLI's `__init__.py`.

## Debugging / Investigation
When investigating issues, explore the full codebase before concluding something is unimplemented or dead code. Check all packages/modules — implementations may exist in unexpected locations (e.g., Terraform configs in a different package or in the `lablink-template` repo).

### Testing
When fixing bugs or adding features, always update existing tests to account for new behavior (e.g., new validation checks, changed function signatures). Run the full test suite before considering a task complete.