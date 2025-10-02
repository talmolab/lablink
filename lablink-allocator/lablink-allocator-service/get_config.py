import logging
import os
from pathlib import Path

from hydra import initialize, compose
from omegaconf import OmegaConf

from conf.structured_config import Config

# Setup logging
logger = logging.getLogger(__name__)


def get_config() -> Config:
    """
    Load the configuration file using Hydra and return it as a dictionary.
    """
    config_dir = os.getenv("CONFIG_DIR", "/config")
    config_name = os.getenv("CONFIG_NAME", "config.yaml")
    runtime_cfg_path = Path(config_dir) / config_name

    if runtime_cfg_path.exists():
        # Get relative path from this file to the config dir
        relative_path = os.path.relpath(config_dir, Path(__file__).parent)
        chosen_path = relative_path
        logger.info(f"Using runtime config from {config_dir}")
        # Remove .yaml from config_name for hydra
        chosen_name = config_name.replace(".yaml", "")
        source = "runtime"
    else:
        chosen_path = "conf"
        chosen_name = "config"
        source = "default"
        logger.info(f"Using {source} config from {chosen_path}")
    with initialize(config_path=chosen_path, version_base=None):
        cfg = compose(config_name=chosen_name)
        logger.debug(OmegaConf.to_yaml(cfg))
        return cfg
