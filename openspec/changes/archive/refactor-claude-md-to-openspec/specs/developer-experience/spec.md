# Developer Experience Specification

## MODIFIED Requirements

### Requirement: CLAUDE.md Structure
The CLAUDE.md file SHALL serve as a concise entry point for AI assistants, pointing to OpenSpec for detailed specifications rather than duplicating content.

#### Scenario: Minimal CLAUDE.md
- **WHEN** an AI assistant reads CLAUDE.md
- **THEN** it finds a brief overview and links to relevant specs
- **AND** the file is under 150 lines

#### Scenario: No duplication with project.md
- **WHEN** comparing CLAUDE.md and openspec/project.md
- **THEN** there is no duplicated content
- **AND** CLAUDE.md references project.md for conventions

#### Scenario: Slash commands are discoverable
- **WHEN** an AI assistant needs to run a development task
- **THEN** CLAUDE.md contains a slash commands reference table
- **AND** each command links to its full documentation

### Requirement: OpenSpec Spec Organization
Project specifications SHALL be organized by capability in `openspec/specs/` with each capability having its own directory.

#### Scenario: API spec exists
- **WHEN** an AI assistant needs to understand API endpoints
- **THEN** it can find `openspec/specs/api/spec.md`
- **AND** the spec documents all endpoints with request/response formats

#### Scenario: Database spec exists
- **WHEN** an AI assistant needs to understand the database schema
- **THEN** it can find `openspec/specs/database/spec.md`
- **AND** the spec documents tables, triggers, and state transitions

#### Scenario: Docker spec exists
- **WHEN** an AI assistant needs to understand Docker image strategy
- **THEN** it can find `openspec/specs/docker/spec.md`
- **AND** the spec documents Dockerfile types, venv setup, and build process

#### Scenario: CI/CD spec exists
- **WHEN** an AI assistant needs to understand CI/CD workflows
- **THEN** it can find `openspec/specs/ci-cd/spec.md`
- **AND** the spec documents workflows, release process, and versioning