from hydra import initialize, compose
from omegaconf import OmegaConf

from conf.structured_config import Config
import logging

# Setup logging
logger = logging.getLogger(__name__)


def get_config() -> Config:
    """
    Load the configuration file using Hydra and return it as a dictionary.
    """
    with initialize(config_path="conf"):
        cfg = compose(config_name="config")
        logger.debug(OmegaConf.to_yaml(cfg))
        return cfg
