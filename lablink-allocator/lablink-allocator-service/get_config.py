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
    chosen_path = "/conf"
    chosen_name = "config"
    with initialize(config_path=chosen_path, version_base=None):
        cfg = compose(config_name=chosen_name)
        logger.debug(OmegaConf.to_yaml(cfg))
        return cfg
