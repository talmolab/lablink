"""Configuration schema for LabLink deployments.

Re-exports the canonical Config dataclass from the allocator package
and adds CLI-specific helpers (YAML serialization, validation, reference data).
"""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path
from typing import Any

import yaml

# Re-export the canonical config dataclasses from the allocator.
from lablink_allocator_service.validate_config import (
    get_config_errors,
)
from lablink_allocator_service.conf.structured_config import (  # noqa: F401
    AllocatorConfig,
    AppConfig,
    BudgetConfig,
    CloudTrailConfig,
    Config,
    DatabaseConfig,
    DNSConfig,
    EIPConfig,
    MachineConfig,
    MonitoringConfig,
    SSLConfig,
    StartupConfig,
    ThresholdsConfig,
)


def config_to_dict(cfg: Any) -> Any:
    """Recursively convert a dataclass to a nested dict."""
    if hasattr(cfg, "__dataclass_fields__"):
        return {
            f.name: config_to_dict(getattr(cfg, f.name))
            for f in fields(cfg)
        }
    return cfg


def load_config(path: Path) -> Config:
    """Load a Config from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)

    cfg = Config()
    for key, value in data.items():
        if hasattr(cfg, key) and isinstance(value, dict):
            sub = getattr(cfg, key)
            for k, v in value.items():
                if isinstance(v, dict):
                    # Nested sub-config (e.g., monitoring.thresholds)
                    nested = getattr(sub, k, None)
                    if nested and hasattr(nested, "__dataclass_fields__"):
                        for nk, nv in v.items():
                            setattr(nested, nk, nv)
                    else:
                        setattr(sub, k, v)
                else:
                    setattr(sub, k, v)
        elif hasattr(cfg, key):
            setattr(cfg, key, value)
    return cfg


def save_config(cfg: Config, path: Path) -> None:
    """Write a Config to a YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(
            config_to_dict(cfg),
            f,
            default_flow_style=False,
            sort_keys=False,
        )


DEPLOYMENT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$")
VALID_ENVIRONMENTS = ("dev", "test", "ci-test", "prod")


def validate_config(cfg: Config) -> list[str]:
    """Return a list of validation errors (empty = valid).

    Mirrors the allocator's validate_config_logic but returns a
    simple list instead of a tuple, suitable for TUI display.
    """
    errors: list[str] = []
    # deployment_name validation
    if not cfg.deployment_name:
        errors.append(
            "deployment_name is required "
            "(e.g., 'sleap-lablink')"
        )
    elif (
        len(cfg.deployment_name) < 3
        or len(cfg.deployment_name) > 32
        or not DEPLOYMENT_NAME_RE.match(cfg.deployment_name)
    ):
        errors.append(
            "deployment_name must be 3-32 characters, "
            "lowercase kebab-case (e.g., 'sleap-lablink')"
        )
    # environment validation
    if cfg.environment not in VALID_ENVIRONMENTS:
        errors.append(
            f"environment must be one of: "
            f"{', '.join(VALID_ENVIRONMENTS)}"
        )
    # DNS/SSL validation — shared with allocator's validate_config
    errors.extend(get_config_errors(cfg))
    return errors


# AMI IDs by region (Ubuntu 24.04 with Docker + Nvidia GPU Driver)
AMI_MAP: dict[str, str] = {
    "us-east-1": "ami-0601752c11b394251",
    "us-east-2": "ami-0601752c11b394251",
    "us-west-1": "ami-0601752c11b394251",
    "us-west-2": "ami-0601752c11b394251",
}

# Common GPU instance types
GPU_INSTANCE_TYPES: list[dict[str, str]] = [
    {
        "type": "g4dn.xlarge",
        "gpu": "T4 16GB",
        "vcpu": "4",
        "ram": "16 GB",
        "cost": "~$0.53/hr",
    },
    {
        "type": "g4dn.2xlarge",
        "gpu": "T4 16GB",
        "vcpu": "8",
        "ram": "32 GB",
        "cost": "~$0.75/hr",
    },
    {
        "type": "g5.xlarge",
        "gpu": "A10G 24GB",
        "vcpu": "4",
        "ram": "16 GB",
        "cost": "~$1.01/hr",
    },
    {
        "type": "g5.2xlarge",
        "gpu": "A10G 24GB",
        "vcpu": "8",
        "ram": "32 GB",
        "cost": "~$1.21/hr",
    },
    {
        "type": "p3.2xlarge",
        "gpu": "V100 16GB",
        "vcpu": "8",
        "ram": "61 GB",
        "cost": "~$3.06/hr",
    },
]

# Common CPU instance types (no GPU)
CPU_INSTANCE_TYPES: list[dict[str, str]] = [
    {
        "type": "t3.large",
        "gpu": "—",
        "vcpu": "2",
        "ram": "8 GB",
        "cost": "~$0.08/hr",
    },
    {
        "type": "t3.xlarge",
        "gpu": "—",
        "vcpu": "4",
        "ram": "16 GB",
        "cost": "~$0.17/hr",
    },
    {
        "type": "t3.2xlarge",
        "gpu": "—",
        "vcpu": "8",
        "ram": "32 GB",
        "cost": "~$0.33/hr",
    },
    {
        "type": "m5.xlarge",
        "gpu": "—",
        "vcpu": "4",
        "ram": "16 GB",
        "cost": "~$0.19/hr",
    },
    {
        "type": "m5.2xlarge",
        "gpu": "—",
        "vcpu": "8",
        "ram": "32 GB",
        "cost": "~$0.38/hr",
    },
]

AWS_REGIONS: list[dict[str, str]] = [
    {"id": "us-east-1", "name": "US East (N. Virginia)"},
    {"id": "us-east-2", "name": "US East (Ohio)"},
    {"id": "us-west-1", "name": "US West (N. California)"},
    {"id": "us-west-2", "name": "US West (Oregon)"},
    {"id": "eu-west-1", "name": "Europe (Ireland)"},
    {"id": "eu-central-1", "name": "Europe (Frankfurt)"},
    {"id": "ap-northeast-1", "name": "Asia Pacific (Tokyo)"},
    {"id": "ap-southeast-1", "name": "Asia Pacific (Singapore)"},
]
