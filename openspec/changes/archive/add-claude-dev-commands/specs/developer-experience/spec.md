# Developer Experience Specification

## ADDED Requirements

### Requirement: Slash Command Discovery
The system SHALL provide discoverable slash commands in the `.claude/commands/` directory that developers can invoke via Claude Code to execute common development tasks.

#### Scenario: Developer lists available commands
- **WHEN** a developer browses the `.claude/commands/` directory
- **THEN** they see markdown files for each available command organized by category

#### Scenario: Developer invokes a command
- **WHEN** a developer types `/test-allocator` in Claude Code
- **THEN** Claude expands the command file content as a prompt with test execution instructions

### Requirement: Testing Commands
The system SHALL provide slash commands for running tests and code quality checks across both packages.

#### Scenario: Run allocator unit tests
- **WHEN** developer invokes `/test-allocator`
- **THEN** command provides instructions to run pytest for allocator package with proper PYTHONPATH

#### Scenario: Run client unit tests
- **WHEN** developer invokes `/test-client`
- **THEN** command provides instructions to run pytest for client package with proper PYTHONPATH

#### Scenario: Run tests with coverage
- **WHEN** developer invokes `/test-coverage`
- **THEN** command provides instructions to run pytest with coverage for both packages, showing coverage percentage

#### Scenario: Run linting checks
- **WHEN** developer invokes `/lint`
- **THEN** command provides instructions to run ruff check on both packages

#### Scenario: Auto-fix linting issues
- **WHEN** developer invokes `/lint-fix`
- **THEN** command provides instructions to run ruff check with --fix flag and ruff format

### Requirement: Docker Build Commands
The system SHALL provide slash commands for building and testing Docker images for both services.

#### Scenario: Build allocator Docker images
- **WHEN** developer invokes `/docker-build-allocator`
- **THEN** command provides instructions to build both Dockerfile.dev (local code) and Dockerfile (from PyPI) with appropriate tags

#### Scenario: Build client Docker images
- **WHEN** developer invokes `/docker-build-client`
- **THEN** command provides instructions to build both dev and prod Docker images with CUDA support

#### Scenario: Test allocator container
- **WHEN** developer invokes `/docker-test-allocator`
- **THEN** command provides instructions to verify allocator container starts, entry points work, and console scripts are available

#### Scenario: Test client container
- **WHEN** developer invokes `/docker-test-client`
- **THEN** command provides instructions to verify client container starts, GPU checks run, and subscription service works

### Requirement: CI/CD Workflow Commands
The system SHALL provide slash commands for triggering GitHub Actions workflows and publishing packages.

#### Scenario: Trigger CI workflow manually
- **WHEN** developer invokes `/trigger-ci`
- **THEN** command provides instructions to use gh CLI to trigger ci.yml workflow

#### Scenario: Trigger Docker image builds
- **WHEN** developer invokes `/trigger-docker-build`
- **THEN** command provides instructions to trigger lablink-images.yml with environment and version parameters

#### Scenario: Publish allocator to PyPI
- **WHEN** developer invokes `/publish-allocator`
- **THEN** command provides instructions to create appropriate git tag and trigger publish-pip.yml workflow

#### Scenario: Publish client to PyPI
- **WHEN** developer invokes `/publish-client`
- **THEN** command provides instructions to create appropriate git tag and trigger publish-pip.yml workflow

### Requirement: PR Management Commands
The system SHALL provide slash commands for generating PR descriptions, reviewing PRs, and maintaining changelogs.

#### Scenario: Generate PR description
- **WHEN** developer invokes `/pr-description`
- **THEN** command instructs Claude to analyze git history since branch divergence and generate structured PR description

#### Scenario: Review pull request
- **WHEN** developer invokes `/review-pr`
- **THEN** command instructs Claude to use planning mode and systematic analysis to review PR changes and post feedback via gh CLI

#### Scenario: Update changelog
- **WHEN** developer invokes `/update-changelog`
- **THEN** command instructs Claude to review recent git commits and update CHANGELOG.md following Keep a Changelog format

### Requirement: Documentation Commands
The system SHALL provide slash commands for serving and building project documentation.

#### Scenario: Serve documentation locally
- **WHEN** developer invokes `/docs-serve`
- **THEN** command provides instructions to run mkdocs serve with proper dependencies

#### Scenario: Build documentation
- **WHEN** developer invokes `/docs-build`
- **THEN** command provides instructions to run mkdocs build for deployment verification

### Requirement: Development Workflow Commands
The system SHALL provide slash commands for common development setup and validation tasks.

#### Scenario: Set up development environment
- **WHEN** developer invokes `/dev-setup`
- **THEN** command provides instructions to install uv, sync dependencies, and verify setup for both packages

#### Scenario: Run allocator locally
- **WHEN** developer invokes `/run-allocator-local`
- **THEN** command provides instructions to run allocator Flask application locally with proper configuration

#### Scenario: Validate Terraform configurations
- **WHEN** developer invokes `/validate-terraform`
- **THEN** command provides instructions to run terraform validate and terraform plan for client VM configurations

### Requirement: Command Documentation Format
Each slash command file SHALL follow a consistent documentation structure for ease of use.

#### Scenario: Command file structure
- **WHEN** a developer reads any command file
- **THEN** it contains title, quick command, detailed explanation, options, expected output, troubleshooting, and related commands

#### Scenario: Cross-platform compatibility
- **WHEN** a command involves platform-specific syntax
- **THEN** the command file documents both Unix/Mac and Windows PowerShell variants

#### Scenario: Command categorization
- **WHEN** viewing the `.claude/commands/` directory
- **THEN** command files are named to indicate their category (test-*, docker-*, pr-*, docs-*, etc.)