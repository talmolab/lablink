import logging
import os
from pathlib import Path
from typing import Optional

from hydra import initialize, compose
from omegaconf import OmegaConf

from lablink_allocator_service.conf.structured_config import Config

# Setup logging
logger = logging.getLogger(__name__)


def get_config(config_path: Optional[str] = None) -> Config:
    """
    Load the configuration file using Hydra and return it as a Config object.

    Args:
        config_path: Optional explicit path to config file. If provided, loads from
                    this path. If None, uses default runtime or bundled config.

    Returns:
        Config object validated against the schema.
    """
    if config_path:
        # Explicit path provided (for validation/testing)
        path = Path(config_path)
        config_dir = path.parent.as_posix()
        config_name = path.stem  # Remove extension
        logger.info(f"Using explicit config from {config_path}")
    else:
        # Use defaults (Docker runtime or bundled)
        config_dir = os.getenv("CONFIG_DIR", "/config")
        config_name = os.getenv("CONFIG_NAME", "config.yaml")
        config_name = config_name.replace(".yaml", "").replace(".yml", "")

    runtime_cfg_path = Path(config_dir) / f"{config_name}.yaml"

    if runtime_cfg_path.exists() or config_path:
        # Get relative path from this file to the config dir
        relative_path = os.path.relpath(config_dir, Path(__file__).parent)
        chosen_path = relative_path
        chosen_name = config_name
        if not config_path:
            logger.info(f"Using runtime config from {config_dir}")
    else:
        # Fall back to bundled config
        chosen_path = "conf"
        chosen_name = "config"
        logger.info(f"Using bundled config from {chosen_path}")

    with initialize(config_path=chosen_path, version_base=None):
        cfg = compose(config_name=chosen_name)
        logger.debug(OmegaConf.to_yaml(cfg))
        return cfg
