# Implementation Tasks

## 1. Create New OpenSpec Specs

### 1.1 API Spec
- [x] Create `openspec/specs/api/spec.md`
- [x] Document all allocator API endpoints
- [x] Include request/response formats
- [x] Add scenarios for each endpoint

### 1.2 Database Spec
- [x] Create `openspec/specs/database/spec.md`
- [x] Document `vms` table schema
- [x] Document triggers (notify_vm_update)
- [x] Add scenarios for state transitions

### 1.3 Docker Spec
- [x] Create `openspec/specs/docker/spec.md`
- [x] Document Dockerfile types (dev vs prod)
- [x] Document venv setup patterns
- [x] Document console scripts
- [x] Add build scenarios

### 1.4 CI/CD Spec
- [x] Create `openspec/specs/ci-cd/spec.md`
- [x] Document workflow overview
- [x] Document release process
- [x] Document versioning conventions
- [x] Add scenarios for each workflow

## 2. Refactor CLAUDE.md

### 2.1 Remove Duplicated Content
- [x] Remove Technology Stack (use project.md)
- [x] Remove Key Concepts (use project.md)
- [x] Remove Configuration System (use project.md)
- [x] Remove Code Style Guidelines (use project.md)
- [x] Remove Testing Strategy (use project.md)

### 2.2 Move to New Specs
- [x] Move Docker Strategy → docker spec
- [x] Move CI/CD Workflows → ci-cd spec
- [x] Move Database Schema → database spec
- [x] Move API Endpoints → api spec
- [x] Move Package Release Process → ci-cd spec

### 2.3 Move to Docs Site or Remove
- [x] Move Common Tasks → rely on slash commands
- [x] Move Troubleshooting → docs site
- [x] Move Documentation System → docs site

### 2.4 Keep and Refine
- [x] Keep OpenSpec instructions block
- [x] Keep brief project overview (shorten)
- [x] Keep repository structure (shorten to essentials)
- [x] Keep slash commands table
- [x] Keep Notes for Claude section
- [x] Add links to specs instead of inline content

## 3. Validation

- [x] Verify CLAUDE.md is ~100 lines or less (96 lines)
- [x] Verify all specs pass `openspec validate --strict`
- [x] Verify no information is lost (just relocated)
- [x] Verify links between files work correctly
- [x] Test that Claude can find information via specs