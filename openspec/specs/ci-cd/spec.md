# CI/CD Specification

## Purpose

Define the continuous integration and deployment workflows for testing, building, and releasing LabLink packages and Docker images.

## Requirements

### Requirement: Continuous Integration Workflow
The `ci.yml` workflow SHALL run on PRs affecting service code.

#### Scenario: Lint check
- **GIVEN** a PR affecting `packages/allocator/**` or `packages/client/**`
- **WHEN** CI runs
- **THEN** `ruff check` executes on both packages
- **AND** the job fails if linting errors exist

#### Scenario: Unit tests
- **GIVEN** a PR affecting package code
- **WHEN** CI runs
- **THEN** `pytest` runs with coverage on both packages
- **AND** coverage must meet 90% threshold

#### Scenario: Docker build test
- **GIVEN** a PR affecting allocator code
- **WHEN** CI runs
- **THEN** `Dockerfile.dev` builds successfully
- **AND** entry points are verified as callable
- **AND** console scripts exist

#### Scenario: Terraform validation
- **GIVEN** a PR affecting allocator Terraform files
- **WHEN** CI runs
- **THEN** `terraform validate` passes
- **AND** `terraform plan` succeeds with fixture data

### Requirement: Docker Image Building Workflow
The `lablink-images.yml` workflow SHALL build and publish Docker images.

#### Scenario: PR/test branch builds
- **GIVEN** a PR or push to test branch
- **WHEN** the workflow runs
- **THEN** `Dockerfile.dev` is used (local code)
- **AND** images are tagged with `-test` suffix

#### Scenario: Main branch builds
- **GIVEN** a push to main branch
- **WHEN** the workflow runs
- **THEN** `Dockerfile` is used (from PyPI)
- **AND** images are tagged `latest` (no version tag)

#### Scenario: Production builds
- **GIVEN** manual dispatch with `environment=prod` and version parameters
- **WHEN** the workflow runs
- **THEN** `Dockerfile` is used with specified PyPI version
- **AND** images are tagged with version numbers

#### Scenario: Post-build verification
- **GIVEN** images are pushed to GHCR
- **WHEN** verification jobs run
- **THEN** entry points are tested as callable
- **AND** console scripts exist
- **AND** package imports work

### Requirement: PyPI Publishing Workflow
The `publish-pip.yml` workflow SHALL publish packages to PyPI.

#### Scenario: Tag-triggered publish
- **GIVEN** a git tag like `lablink-allocator-service_v0.0.2a0`
- **WHEN** pushed from main branch
- **THEN** the workflow:
  - Verifies branch is main
  - Verifies tag version matches pyproject.toml
  - Runs linting and tests
  - Builds and publishes to PyPI

#### Scenario: Version mismatch
- **GIVEN** a tag with version not matching pyproject.toml
- **WHEN** the workflow runs
- **THEN** the workflow fails with version mismatch error

#### Scenario: Dry run mode
- **GIVEN** manual dispatch with `dry_run=true`
- **WHEN** the workflow runs
- **THEN** all steps execute except PyPI upload

### Requirement: Documentation Workflow
The `docs.yml` workflow SHALL build and deploy documentation.

#### Scenario: Main branch docs deployment
- **GIVEN** a push to main affecting docs
- **WHEN** the workflow runs
- **THEN** MkDocs builds successfully
- **AND** deploys to GitHub Pages

#### Scenario: PR docs validation
- **GIVEN** a PR affecting `docs/`
- **WHEN** the workflow runs
- **THEN** MkDocs builds successfully (validation only)

### Requirement: Release Process
Releases SHALL follow a defined multi-step process.

#### Scenario: Development to merge
- **GIVEN** a feature branch with changes
- **WHEN** a PR is created
- **THEN** CI runs tests, lint, and Docker build
- **AND** dev images are built with `-test` suffix

#### Scenario: PyPI publication
- **GIVEN** code merged to main
- **WHEN** a version tag is created and pushed
- **THEN** `publish-pip.yml` publishes to PyPI

#### Scenario: Production image creation
- **GIVEN** package published to PyPI
- **WHEN** manual dispatch triggered with version
- **THEN** production Docker images are built with version tags

### Requirement: Semantic Versioning
Package versions SHALL follow semantic versioning.

#### Scenario: Version format
- **GIVEN** a package version
- **WHEN** formatted
- **THEN** it follows semver: `MAJOR.MINOR.PATCH` or `MAJOR.MINOR.PATCHaN` for alpha

#### Scenario: Tag convention
- **GIVEN** a release tag
- **WHEN** formatted
- **THEN** it follows: `{package-name}_v{version}`
- **EXAMPLE** `lablink-allocator-service_v0.0.2a0`