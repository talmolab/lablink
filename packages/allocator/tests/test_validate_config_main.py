import sys
from unittest.mock import patch
import pytest
from lablink_allocator_service.validate_config import main


@pytest.fixture
def mock_validate_config():
    """Fixture to mock the core validate_config function."""
    with patch("lablink_allocator_service.validate_config.validate_config") as mock:
        yield mock


def test_main_success(mock_validate_config, capsys):
    """Test the main CLI entry point with a successful validation."""
    mock_validate_config.return_value = (True, "[PASS] Config is valid")

    with patch.object(sys, "argv", ["lablink-validate-config", "/fake/config.yaml"]):
        with pytest.raises(SystemExit) as e:
            main()

    outerr = capsys.readouterr()
    assert "[PASS] Config is valid" in outerr.out
    assert e.value.code == 0
    mock_validate_config.assert_called_once_with("/fake/config.yaml")


def test_main_failure(mock_validate_config, capsys):
    """Test the main CLI entry point with a failed validation."""
    mock_validate_config.return_value = (False, "[FAIL] Invalid config")

    with patch.object(sys, "argv", ["lablink-validate-config", "/fake/invalid.yaml"]):
        with pytest.raises(SystemExit) as e:
            main()

    outerr = capsys.readouterr()
    assert "[FAIL] Invalid config" in outerr.out
    assert e.value.code == 1
    mock_validate_config.assert_called_once_with("/fake/invalid.yaml")


def test_main_default_path(mock_validate_config):
    """Test that the default config path is used when none is provided."""
    mock_validate_config.return_value = (True, "Default path works")

    with patch.object(sys, "argv", ["lablink-validate-config"]):
        with pytest.raises(SystemExit):
            main()

    mock_validate_config.assert_called_once_with("/config/config.yaml")


def test_main_help_message(capsys):
    """Test that the help message is displayed with -h."""
    with patch.object(sys, "argv", ["lablink-validate-config", "-h"]):
        with pytest.raises(SystemExit) as e:
            main()

    outerr = capsys.readouterr()
    assert "Validate LabLink allocator configuration file" in outerr.out
    assert e.value.code == 0
