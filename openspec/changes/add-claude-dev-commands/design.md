# Design: Claude Development Commands

## Context

LabLink is a Python monorepo with two packages (allocator and client), each with its own tests, Docker images, and deployment workflows. Developers need quick access to common tasks like testing, building images, and managing PRs. Claude Code supports slash commands (`.claude/commands/*.md`) that expand to prompt templates, providing instant access to standardized workflows.

The GAPIT3 GWAS pipeline project has successfully implemented similar commands, providing a proven pattern to follow.

## Goals / Non-Goals

### Goals
- Provide instant access to common development tasks via slash commands
- Standardize workflows across the team (testing, linting, Docker builds, PR management)
- Reduce cognitive load by documenting command patterns in discoverable files
- Support both monorepo packages (allocator and client) with appropriate commands
- Enable cross-platform compatibility (Windows and Unix-like systems)
- Follow established patterns from GAPIT3 pipeline where applicable

### Non-Goals
- Not creating custom tooling or scripts (commands use existing tools: pytest, ruff, docker, gh CLI)
- Not modifying CI/CD workflows (commands trigger existing workflows)
- Not changing code structure or architecture
- Not creating interactive shells or TUIs (commands are documentation that expands to prompts)

## Decisions

### Decision 1: Slash Command Structure
**Choice**: Create separate command files per task in `.claude/commands/*.md`

**Rationale**:
- Each command is a markdown file containing documentation and instructions
- Claude Code reads these files and expands them as prompts when invoked
- Separate files allow independent maintenance and discovery
- Follows established pattern from GAPIT3 pipeline

**Alternatives Considered**:
- **Single commands file**: Would be harder to maintain and navigate
- **Bash scripts**: Less flexible than prompt-based commands, harder to adapt to context

### Decision 2: Command Categories
**Choice**: Organize commands into logical categories:
1. Testing & Validation (test, lint)
2. Docker (build, test containers)
3. CI/CD (trigger workflows, publish packages)
4. Git & PR (description generation, reviews, changelog)
5. Documentation (serve, build)
6. Development Workflow (setup, local run, validation)

**Rationale**:
- Matches natural developer workflows and task groupings
- Aligns with LabLink's architecture (packages, Docker, CI/CD, docs)
- Easy to discover related commands

### Decision 3: Monorepo Package Support
**Choice**: Create both unified commands (`/test-coverage`, `/lint`) and package-specific commands (`/test-allocator`, `/test-client`)

**Rationale**:
- Unified commands: Faster when working on both packages or doing comprehensive checks
- Package-specific commands: Faster feedback when working on single package
- Provides flexibility for different development contexts

**Example**:
- `/test-allocator` → Run only allocator tests (fast iteration)
- `/test-coverage` → Run both packages with coverage (pre-PR check)

### Decision 4: Docker Build Commands
**Choice**: Separate commands for dev vs prod builds, separate commands per package

**Commands**:
- `/docker-build-allocator`: Builds both `Dockerfile.dev` and `Dockerfile` for allocator
- `/docker-build-client`: Builds both dev and prod images for client
- `/docker-test-allocator`: Test allocator container functionality
- `/docker-test-client`: Test client container functionality

**Rationale**:
- Dev builds (Dockerfile.dev): Use local code, faster iteration, include dev dependencies
- Prod builds (Dockerfile): Use PyPI packages, require version specification
- Separate per package: Client images are large (~6GB), allocator faster to build
- Allows developers to build only what they need

### Decision 5: CI/CD Trigger Commands
**Choice**: Provide manual workflow trigger commands using `gh workflow run`

**Rationale**:
- GitHub CLI (`gh`) is already used in the project
- Manual triggers useful for testing workflow changes
- Provides visibility into workflow inputs (versions, environments)
- Complements automatic triggers (PR, push, tags)

### Decision 6: PR Management Commands
**Choice**: Adapt GAPIT3 pipeline's `/pr-description` and `/review-pr` commands for LabLink

**Rationale**:
- These commands are proven to improve PR quality
- `/pr-description`: Analyzes git history and generates structured PR template
- `/review-pr`: Uses planning mode and structured analysis for comprehensive reviews
- Reduces time spent writing PR descriptions and reviewing code

### Decision 7: Cross-Platform Compatibility
**Choice**: Use platform-agnostic patterns where possible, note platform differences in commands

**Patterns**:
- Use `${PWD}` for Docker volume mounts (works in PowerShell and bash)
- Provide Windows-specific examples where needed (e.g., PowerShell syntax)
- Use `gh` CLI which works across platforms
- Document platform-specific issues (path separators, line endings)

**Example from `/docker-test-allocator`**:
```bash
# Unix/Mac
docker run --rm -v $(pwd)/tests:/tests image:dev

# Windows PowerShell
docker run --rm -v ${PWD}/tests:/tests image:dev
```

### Decision 8: Command Documentation Format
**Choice**: Each command file contains:
1. Title/description
2. Quick command (copy-paste ready)
3. Detailed explanation
4. Common options/variations
5. Expected output
6. Troubleshooting
7. Related commands

**Rationale**:
- Matches GAPIT3 pipeline pattern (proven to work well)
- Provides both quick reference and detailed learning
- Self-contained documentation reduces need to search elsewhere

## Risks / Trade-offs

### Risk 1: Command Duplication with CLAUDE.md
**Mitigation**:
- CLAUDE.md provides project context and architecture
- Commands provide task-specific execution patterns
- Commands reference CLAUDE.md for deeper context
- Clear separation: CLAUDE.md = "what/why", commands = "how"

### Risk 2: Command Maintenance Burden
**Mitigation**:
- Commands are documentation, not code (lower maintenance)
- Update commands when workflows change (part of normal PR process)
- OpenSpec change proposals ensure command updates are tracked

### Risk 3: Cross-Platform Issues
**Mitigation**:
- Document platform-specific variations in each command
- Test commands on both Windows and Unix-like systems (task 8.2)
- Use platform-agnostic tools (gh CLI, docker, python) where possible

### Trade-off: Comprehensive vs Minimal Command Set
**Decision**: Start with comprehensive set (16+ commands)

**Reasoning**:
- Upfront cost is writing documentation (relatively low)
- Having unused commands is better than missing critical ones
- Commands are discoverable (developers can browse `.claude/commands/`)
- Can deprecate unused commands later based on usage patterns

## Migration Plan

### Phase 1: Initial Implementation
1. Create all command files in `.claude/commands/`
2. Test each command manually on local environment
3. Update CLAUDE.md with references to new commands

### Phase 2: Team Adoption
1. Announce new commands in team communication
2. Update onboarding documentation to mention slash commands
3. Gather feedback on command usefulness

### Phase 3: Iteration
1. Refine commands based on usage patterns
2. Add new commands as needed
3. Remove or consolidate rarely-used commands

### Rollback
- Simple: Delete `.claude/commands/` directory
- No code dependencies, no infrastructure changes
- Zero risk rollback

## Open Questions

1. **Should we add commands for specific debugging scenarios?**
   - Examples: Database connection testing, AWS credential validation
   - **Decision**: Start without these, add if requested

2. **Should we include commands for infrastructure deployment?**
   - Examples: Deploy to test environment, deploy to prod
   - **Decision**: No - infrastructure deployment is in lablink-template repo, separate concern

3. **Should we add commands for dependency management?**
   - Examples: Update dependencies, check for security vulnerabilities
   - **Decision**: Add `/dev-setup` for initial setup, skip specific dependency commands for now

4. **Should commands include interactive prompts or be purely informational?**
   - **Decision**: Purely informational/instructional (Claude expands command as prompt)
   - Claude Code handles any interactivity based on expanded prompt