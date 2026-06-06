"""GPU sampler.

Polls nvidia-smi for current utilization (%) and VRAM used (MB).
Returns (0, 0) when nvidia-smi is missing or fails — agent must not
crash on a non-GPU dev host.
"""

import logging
import subprocess

logger = logging.getLogger(__name__)


def sample() -> tuple[int, int]:
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        logger.debug("nvidia-smi probe failed: %s", e)
        return 0, 0

    if out.returncode != 0:
        return 0, 0
    line = out.stdout.strip().splitlines()[0] if out.stdout.strip() else ""
    if not line:
        return 0, 0
    try:
        util_s, vram_s = (p.strip() for p in line.split(","))
        return int(util_s), int(vram_s)
    except (ValueError, IndexError) as e:
        logger.debug("nvidia-smi parse failed (%r): %s", line, e)
        return 0, 0
