# Proposal: Validate AWS Region Configuration

**Change ID**: `validate-aws-region`
**Status**: Draft
**Author**: Elizabeth
**Created**: 2025-11-11

## Problem Statement

The allocator service requires a valid AWS region for critical operations:
- Terraform backend configuration (S3 state storage)
- AWS API calls (EC2, CloudWatch Logs)
- Client VM provisioning

Currently, there is no validation of the `app.region` configuration field. Invalid or missing regions cause runtime failures that could be caught at deployment time via config validation.

**Examples of issues prevented:**
- Empty region string → Terraform init fails
- Typo (e.g., `us-west-3` instead of `us-west-2`) → AWS API errors
- Invalid format (e.g., `uswest2`) → Runtime failures
- Wrong region type (e.g., `cn-north-1` without proper AWS China credentials)

## Proposed Solution

Add AWS region format validation to the existing `validate_config.py` module:

1. **Region Format Validation**: Validate that region follows AWS naming conventions
2. **Required Field Check**: Ensure region is non-empty when AWS features are used
3. **Pre-deployment Detection**: Fail fast during CI/CD before infrastructure deployment

## Scope

### In Scope
- Add `validate_aws_region()` function to check region format
- Integrate region validation into `validate_config_logic()`
- Add test coverage for valid and invalid regions
- Support all standard AWS regions and special regions (GovCloud, China)

### Out of Scope
- Runtime AWS API calls to verify region exists (would require credentials)
- Region-specific feature validation (e.g., checking if instance type available in region)
- Automatic region detection or suggestion

## Changes

### 1. Add Region Format Validation Function

**Location**: `packages/allocator/src/lablink_allocator_service/validate_config.py`

Add a new validation function:
```python
def validate_aws_region(region: str) -> Tuple[bool, str]:
    """Validate AWS region format."""
```

**Validation Rules**:
- Non-empty string required
- Must match AWS region pattern: `<geo>-<direction>-<number>`
- Examples: `us-west-2`, `eu-central-1`, `ap-southeast-1`
- Support special regions: `us-gov-*`, `cn-north-*`, `cn-northwest-*`

### 2. Integrate into Config Validation

Update `validate_config_logic()` to call `validate_aws_region(cfg.app.region)` and append any errors to the validation error list.

### 3. Add Test Coverage

**Location**: `packages/allocator/tests/test_validate_config.py`

Add tests for:
- Valid standard regions (us-west-2, eu-central-1, ap-southeast-1)
- Valid special regions (us-gov-west-1, cn-north-1)
- Invalid: empty region
- Invalid: malformed format (missing hyphens, wrong pattern)
- Invalid: typos (us-west-3, eu-central-2)

## Implementation Plan

See `tasks.md` for detailed implementation steps.

## Dependencies

- Existing config validation framework (`validate_config.py`)
- Hydra/OmegaConf configuration system
- pytest test suite

## Breaking Changes

None. This is additive validation that will catch previously-ignored misconfigurations.

## Migration Path

No migration required. Existing valid configurations will continue to work. Invalid configurations that previously failed at runtime will now fail at validation time (better developer experience).

## Success Criteria

- [ ] Region validation function implemented
- [ ] Validation integrated into `validate_config_logic()`
- [ ] All tests passing (existing + new)
- [ ] Invalid regions caught during `lablink-validate-config` execution
- [ ] CI validation prevents deployment with invalid regions