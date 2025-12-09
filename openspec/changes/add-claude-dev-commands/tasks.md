# Implementation Tasks

## 1. Setup and Structure
- [x] 1.1 Create `.claude/commands/` directory structure
- [x] 1.2 Add `.claude/commands/README.md` documenting command conventions
- [x] 1.3 Update `CLAUDE.md` to reference new slash commands

## 2. Testing Commands
- [x] 2.1 Create `/test-allocator` command for running allocator unit tests
- [x] 2.2 Create `/test-client` command for running client unit tests
- [x] 2.3 Create `/test-coverage` command for coverage analysis across both packages
- [x] 2.4 Create `/lint` command for running ruff checks on both packages
- [x] 2.5 Create `/lint-fix` command for auto-fixing linting issues

## 3. Docker Commands
- [x] 3.1 Create `/docker-build-allocator` command for allocator image builds
- [x] 3.2 Create `/docker-build-client` command for client image builds
- [x] 3.3 Create `/docker-test-allocator` command for allocator container testing
- [x] 3.4 Create `/docker-test-client` command for client container testing

## 4. CI/CD Commands
- [x] 4.1 Create `/trigger-ci` command for manual CI workflow dispatch
- [x] 4.2 Create `/trigger-docker-build` command for Docker image workflow
- [x] 4.3 Create `/publish-allocator` command for PyPI publishing
- [x] 4.4 Create `/publish-client` command for PyPI publishing

## 5. Git & PR Commands
- [x] 5.1 Create `/pr-description` command for generating PR descriptions
- [x] 5.2 Create `/review-pr` command for comprehensive PR reviews
- [x] 5.3 Create `/update-changelog` command for CHANGELOG maintenance

## 6. Documentation Commands
- [x] 6.1 Create `/docs-serve` command for local documentation preview
- [x] 6.2 Create `/docs-build` command for documentation deployment

## 7. Development Workflow Commands
- [x] 7.1 Create `/dev-setup` command for environment initialization
- [x] 7.2 Create `/run-allocator-local` command for local allocator testing
- [x] 7.3 Create `/validate-terraform` command for Terraform validation

## 8. Validation and Documentation
- [x] 8.1 Test all commands in local development environment
- [x] 8.2 Verify commands work on both Windows and Unix-like systems
- [x] 8.3 Update documentation site with slash command reference page
- [x] 8.4 Add examples to `CLAUDE.md` showing command usage