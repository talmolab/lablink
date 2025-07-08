import subprocess
import logging

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(name)s: %(message)s",
    datefmt="%H:%M",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


def check_gpu_health():
    """Check the health of the GPU.

    Args:
        interval (int, optional): The interval in seconds to check the GPU health. Defaults to 20.
    """
    try:
        # Run the nvidia-smi command to check GPU health
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        logger.info(f"GPU Health Check: {result.stdout.strip()}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to check GPU health: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
    check_gpu_health()
    logger.info("GPU health check completed.")
