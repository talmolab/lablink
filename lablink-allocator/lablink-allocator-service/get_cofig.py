from hydra import initialize, compose
from omegaconf import OmegaConf
from conf.structured_config import Config
import logging

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def get_config() -> Config:
    """
    Load the configuration file using Hydra and return it as a dictionary.
    """
    with initialize(config_path="conf"):
        cfg = compose(config_name="config")
        print(OmegaConf.to_yaml(cfg))
        return cfg
