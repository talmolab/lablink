"""Config validation CLI for LabLink Allocator Service.

This module provides a command-line tool to validate configuration files
against the Hydra/OmegaConf schema before deployment. This enables fail-fast
validation during CI/CD pipelines.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Tuple

from hydra.errors import ConfigCompositionException
from omegaconf.errors import ConfigKeyError, ValidationError

from lablink_allocator_service.get_config import get_config

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(message)s",
)
logger = logging.getLogger(__name__)


def validate_config(config_path: str) -> Tuple[bool, str]:
    """Validate a configuration file against the schema.

    Args:
        config_path: Path to the config.yaml file to validate

    Returns:
        Tuple of (is_valid, message):
            - is_valid: True if config is valid, False otherwise
            - message: Success or error message
    """
    path = Path(config_path)

    # Check if file exists
    if not path.exists():
        return False, f"[FAIL] Config file not found: {config_path}"

    if not path.is_file():
        return False, f"[FAIL] Config path is not a file: {config_path}"

    # Require config.yaml filename for Hydra schema matching
    if path.name != "config.yaml":
        return False, (
            f"[FAIL] Config file must be named 'config.yaml'\n"
            f"       Found: {path.name}\n"
            f"       Rename your file to enable strict schema validation"
        )

    try:
        # Use get_config() with explicit path - it validates automatically
        get_config(config_path=str(path))
        return True, "[PASS] Config validation passed"

    except ConfigCompositionException as e:
        # This is the error from your Docker logs - extract the key info
        error_msg = "[FAIL] Config validation failed: Error merging config with schema\n"
        error_str = str(e)

        # Try to extract the key that caused the problem
        if "Key '" in error_str and "' not in" in error_str:
            # Extract key name from error message
            key_start = error_str.find("Key '") + 5
            key_end = error_str.find("'", key_start)
            bad_key = error_str[key_start:key_end]
            error_msg += f"       Unknown key: '{bad_key}'\n"
            error_msg += "       This key is not defined in the Config schema\n"
        else:
            error_msg += f"       {error_str}\n"

        return False, error_msg

    except ConfigKeyError as e:
        error_msg = "[FAIL] Config validation failed: Unknown configuration key\n"
        error_msg += f"       Key '{e.key}' not found in schema"
        if hasattr(e, "full_key") and e.full_key:
            error_msg += f"\n       Full key path: {e.full_key}"
        if hasattr(e, "object_type") and e.object_type:
            type_name = (
                e.object_type.__name__
                if hasattr(e.object_type, "__name__")
                else str(e.object_type)
            )
            error_msg += f"\n       Expected in schema: {type_name}"
        error_msg += "\n"
        return False, error_msg

    except ValidationError as e:
        error_msg = "[FAIL] Config validation failed: Schema validation error\n"
        error_msg += f"       {str(e)}\n"
        return False, error_msg

    except Exception as e:
        logger.exception("Unexpected error during config validation")
        error_msg = f"[FAIL] Config validation failed: {type(e).__name__}\n"
        error_msg += f"       {str(e)}\n"
        return False, error_msg


def main():
    """Main entry point for the config validation CLI."""
    parser = argparse.ArgumentParser(
        description="Validate LabLink allocator configuration file against schema",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate deployment config
  lablink-validate-config config/config.yaml

  # Validate runtime config in Docker
  lablink-validate-config /config/config.yaml

  # Validate bundled config
  lablink-validate-config \\
      packages/allocator/src/lablink_allocator_service/conf/config.yaml

NOTE: Config file MUST be named 'config.yaml' for schema validation.

Exit codes:
  0 - Config is valid
  1 - Config is invalid or error occurred
        """,
    )

    parser.add_argument(
        "config_path",
        nargs="?",
        default="/config/config.yaml",
        help="Path to the config.yaml file to validate (default: /config/config.yaml)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    # Set logging level based on verbosity
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger("lablink_allocator_service").setLevel(logging.INFO)

    # Validate the configuration
    is_valid, message = validate_config(args.config_path)

    # Print the result
    print(message)

    # Exit with appropriate code
    sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
