"""Tests for config validation CLI."""

import lablink_allocator_service.validate_config as vc_module
from lablink_allocator_service.validate_config import validate_config


def test_validate_valid_config(valid_config_dict, write_config_file):
    """Test that a valid config with allocator.image_tag passes validation."""
    config_path = write_config_file(valid_config_dict)

    is_valid, message = validate_config(config_path)

    assert is_valid is True
    assert "[PASS]" in message
    assert "passed" in message.lower()


def test_validate_invalid_config_unknown_key(invalid_config_dict, write_config_file):
    """Test that config with unknown key fails validation (recreates Docker error)."""
    config_path = write_config_file(invalid_config_dict)

    is_valid, message = validate_config(config_path)

    assert is_valid is False
    assert "[FAIL]" in message
    assert "failed" in message.lower()
    # Should mention the unknown key
    assert "unknown" in message.lower() or "schema" in message.lower()


def test_validate_missing_file(tmp_path):
    """Test that validation fails gracefully when file doesn't exist."""
    nonexistent_path = str(tmp_path / "nonexistent.yaml")

    is_valid, message = validate_config(nonexistent_path)

    assert is_valid is False
    assert "not found" in message.lower()
    assert nonexistent_path in message


def test_validate_directory_not_file(tmp_path):
    """Test that validation fails when path is a directory."""
    is_valid, message = validate_config(str(tmp_path))

    assert is_valid is False
    assert "not a file" in message.lower()


def test_validate_invalid_yaml_syntax(tmp_path):
    """Test that validation fails on malformed YAML."""
    invalid_yaml_path = tmp_path / "invalid.yaml"
    with open(invalid_yaml_path, "w") as f:
        f.write("this is not: valid: yaml: syntax\n  [\ninvalid indentation")

    is_valid, message = validate_config(str(invalid_yaml_path))

    assert is_valid is False
    assert "[FAIL]" in message


def test_validate_config_with_allocator_image_tag(valid_config_dict, write_config_file):
    """Test that allocator.image_tag field is accepted in schema."""
    # This is the key test - ensure the allocator section validates
    assert "allocator" in valid_config_dict
    assert "image_tag" in valid_config_dict["allocator"]

    config_path = write_config_file(valid_config_dict)
    is_valid, message = validate_config(config_path)

    assert is_valid is True
    assert "[PASS]" in message


def test_unknown_top_level_key_behavior(
    config_with_unknown_top_level_key, write_config_file
):
    """Test validation behavior with unknown top-level key (terraform_vars).

    This test documents whether Hydra catches unknown keys by default.
    The 'terraform_vars' key does NOT exist in the Config schema.
    """
    config_path = write_config_file(config_with_unknown_top_level_key)
    is_valid, message = validate_config(config_path)

    # Print the result for documentation
    print("\nUnknown top-level key validation result:")
    print(f"  Valid: {is_valid}")
    print(f"  Message: {message}")

    # Validation should FAIL for unknown keys (Hydra catches them)
    assert is_valid is False
    assert "[FAIL]" in message
    assert "schema" in message.lower() or "merging" in message.lower()


def test_unknown_nested_key_behavior(
    config_with_unknown_nested_key, write_config_file
):
    """Test validation behavior with unknown nested key (db.unknown_field).

    This test documents whether Hydra catches unknown nested fields.
    The 'unknown_field' key does NOT exist in DatabaseConfig schema.
    """
    config_path = write_config_file(config_with_unknown_nested_key)
    is_valid, message = validate_config(config_path)

    # Print the result for documentation
    print("\nUnknown nested key validation result:")
    print(f"  Valid: {is_valid}")
    print(f"  Message: {message}")

    # Validation should FAIL for unknown nested keys (Hydra catches them)
    assert is_valid is False
    assert "[FAIL]" in message
    assert "schema" in message.lower() or "merging" in message.lower()


def test_wrong_filename_rejected(valid_config_dict, write_config_file):
    """Test that non-config.yaml filenames are rejected."""
    config_path = write_config_file(valid_config_dict, filename="wrong_name.yaml")

    is_valid, message = validate_config(config_path)

    assert is_valid is False
    assert "must be named 'config.yaml'" in message.lower()
    assert "wrong_name.yaml" in message


def test_type_mismatch_validation_error(valid_config_dict, write_config_file):
    """Test ValidationError when config has type mismatch (e.g., string for int)."""
    config = valid_config_dict.copy()
    # Port should be int, but we'll provide a string
    config["db"]["port"] = "not_an_integer"

    config_path = write_config_file(config)
    is_valid, message = validate_config(config_path)

    # This should fail validation
    assert is_valid is False
    assert "[FAIL]" in message
    # Could be ValidationError or ConfigCompositionException
    assert "failed" in message.lower()


def test_generic_exception_handling(monkeypatch, valid_config_dict, write_config_file):
    """Test that unexpected exceptions are caught and reported."""
    # Create a valid config file first
    config_path = write_config_file(valid_config_dict)

    # Mock get_config to raise an unexpected error
    def mock_get_config(*args, **kwargs):
        raise RuntimeError("Simulated unexpected error")

    monkeypatch.setattr(vc_module, "get_config", mock_get_config)

    is_valid, message = validate_config(config_path)

    assert is_valid is False
    assert "[FAIL]" in message
    assert "RuntimeError" in message
    assert "unexpected error" in message.lower()
