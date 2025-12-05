# Tasks: Validate AWS Region Configuration

**Change ID**: `validate-aws-region`

## Implementation Tasks

### 1. Add Region Validation Function
**File**: `packages/allocator/src/lablink_allocator_service/validate_config.py`

- [ ] Add `validate_aws_region(region: str) -> Tuple[bool, str]` function
- [ ] Implement empty region check
- [ ] Implement AWS region format validation (pattern: `<geo>-<direction>-<number>`)
- [ ] Support standard regions: us-*, eu-*, ap-*, ca-*, sa-*, af-*, me-*
- [ ] Support special regions: us-gov-*, cn-north-*, cn-northwest-*
- [ ] Return descriptive error messages for invalid formats

### 2. Integrate into Config Validation Logic
**File**: `packages/allocator/src/lablink_allocator_service/validate_config.py`

- [ ] Call `validate_aws_region(cfg.app.region)` in `validate_config_logic()`
- [ ] Append region validation errors to error list
- [ ] Ensure proper error message formatting

### 3. Add Test Coverage
**File**: `packages/allocator/tests/test_validate_config.py`

- [ ] Test: Valid standard regions
  - `us-west-2`
  - `us-east-1`
  - `eu-central-1`
  - `ap-southeast-1`
- [ ] Test: Valid special regions
  - `us-gov-west-1`
  - `cn-north-1`
- [ ] Test: Empty region fails validation
- [ ] Test: Malformed regions fail validation
  - Missing hyphens: `uswest2`
  - Wrong pattern: `west-us-2`
  - Invalid prefix: `xx-west-2`
- [ ] Test: Common typos fail validation
  - `us-west-3` (doesn't exist)
  - `eu-central-2` (doesn't exist as of validation implementation)

### 4. Validation and Testing

- [ ] Run all existing tests: `PYTHONPATH=. pytest packages/allocator/tests/`
- [ ] Verify new tests pass
- [ ] Test with valid config: `lablink-validate-config packages/allocator/src/lablink_allocator_service/conf/config.yaml`
- [ ] Test with invalid region in config (manual test)
- [ ] Verify error messages are clear and actionable

### 5. Documentation

- [ ] Add region validation to validation logic docstring
- [ ] Update function docstrings with examples
- [ ] Add inline comments explaining AWS region patterns

## Testing Checklist

- [ ] Unit tests for `validate_aws_region()` function
- [ ] Integration tests in `validate_config_logic()`
- [ ] Manual testing with valid and invalid configs
- [ ] Verify existing functionality unchanged (regression test)

## Dependencies

None. This change is self-contained within the validation module.

## Estimated Effort

- Implementation: 30 minutes
- Testing: 30 minutes
- Total: ~1 hour