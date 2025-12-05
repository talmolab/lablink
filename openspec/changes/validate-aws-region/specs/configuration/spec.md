# Spec: Configuration Validation - AWS Region

**Capability**: Configuration Validation
**Change ID**: `validate-aws-region`
**Status**: Draft

## Overview

This spec defines requirements for validating AWS region configuration to prevent deployment failures caused by invalid or missing region values.

---

## ADDED Requirements

### Requirement: AWS Region Format Validation

The configuration validator MUST validate that the `app.region` field follows AWS region naming conventions.

#### Scenario: Valid standard AWS regions pass validation

**Given** a config with `app.region` set to a valid standard AWS region
**When** validation runs
**Then** validation passes

**Examples of valid regions**:
- `us-west-2`
- `us-east-1`
- `eu-central-1`
- `eu-west-1`
- `ap-southeast-1`
- `ap-northeast-1`
- `ca-central-1`
- `sa-east-1`
- `af-south-1`
- `me-south-1`

#### Scenario: Valid special AWS regions pass validation

**Given** a config with `app.region` set to a valid special AWS region (GovCloud or China)
**When** validation runs
**Then** validation passes

**Examples of valid special regions**:
- `us-gov-west-1`
- `us-gov-east-1`
- `cn-north-1`
- `cn-northwest-1`

#### Scenario: Empty region fails validation

**Given** a config with `app.region` set to empty string
**When** validation runs
**Then** validation fails with error "AWS region is required"

#### Scenario: Malformed region format fails validation

**Given** a config with `app.region` that doesn't follow AWS naming pattern
**When** validation runs
**Then** validation fails with descriptive error message

**Examples of invalid formats**:
- `uswest2` (missing hyphens)
- `west-us-2` (wrong order)
- `us-west` (missing number)
- `us-west-2-extra` (extra suffix)
- `xx-west-2` (invalid geographic prefix)

#### Scenario: Region with typo fails validation

**Given** a config with `app.region` containing a common typo
**When** validation runs
**Then** validation fails with format error

**Examples**:
- `us-west-3` (us-west only has 1 and 2)
- `us-central-1` (should be ca-central-1 for Canada)
- `europe-west-1` (should be eu-west-1)

---

### Requirement: Region Validation Error Messages

The validator MUST provide clear, actionable error messages for invalid region configurations.

#### Scenario: Error message shows expected format

**Given** an invalid region format
**When** validation fails
**Then** error message includes expected format pattern
**And** error message includes example valid regions

**Example error message**:
```
Invalid AWS region format: 'uswest2'
Expected format: <geo>-<direction>-<number> (e.g., us-west-2, eu-central-1)
```

#### Scenario: Error message includes actual invalid value

**Given** an invalid region value
**When** validation fails
**Then** error message quotes the actual invalid value provided

**Example**:
```
Invalid AWS region format: 'xx-west-2'
```

---

### Requirement: Region Validation Integration

The region validation MUST be integrated into the main `validate_config_logic()` function.

#### Scenario: Region errors included in validation summary

**Given** a config with both an invalid region and other validation errors
**When** validation runs
**Then** all errors are collected and reported together
**And** region error is listed alongside other errors

#### Scenario: Region validation runs on every config check

**Given** the `lablink-validate-config` CLI is invoked
**When** config validation executes
**Then** region validation is performed
**And** results are included in validation output

---

## Test Coverage Requirements

### Requirement: Comprehensive Region Validation Tests

The test suite MUST include tests covering all region validation scenarios.

#### Scenario: Valid regions test coverage

**Given** test suite for config validation
**Then** tests exist for at least 3 standard AWS regions
**And** tests exist for at least 2 special AWS regions (GovCloud, China)
**And** all valid region tests pass

#### Scenario: Invalid regions test coverage

**Given** test suite for config validation
**Then** tests exist for empty region
**And** tests exist for malformed format (at least 3 cases)
**And** tests exist for common typos (at least 2 cases)
**And** all invalid region tests correctly fail validation