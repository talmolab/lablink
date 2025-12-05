"""Configuration helper functions for building URLs and determining settings."""

import os
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


def get_allocator_url(cfg, allocator_ip: str) -> Tuple[str, str]:
    """
    Build the allocator URL based on configuration.

    Priority order:
    1. ALLOCATOR_FQDN environment variable (set by Terraform)
    2. DNS configuration from config
    3. IP address fallback

    Args:
        cfg: Hydra configuration object
        allocator_ip: Public IP address of allocator

    Returns:
        Tuple of (base_url, protocol)

    Examples:
        ALLOCATOR_FQDN environment variable:
            ("https://test.lablink.sleap.ai", "https")

        DNS enabled + Let's Encrypt SSL:
            ("https://test.lablink.sleap.ai", "https")

        DNS disabled + No SSL:
            ("http://52.40.142.146", "http")
    """
    # Priority 1: Check for ALLOCATOR_FQDN environment variable (set by Terraform)
    allocator_fqdn = os.getenv("ALLOCATOR_FQDN")
    if allocator_fqdn:
        # FQDN already includes protocol
        if allocator_fqdn.startswith("https://"):
            protocol = "https"
        elif allocator_fqdn.startswith("http://"):
            protocol = "http"
        else:
            # Default to http if no protocol specified
            protocol = "http"
            allocator_fqdn = f"{protocol}://{allocator_fqdn}"

        logger.info(f"Using ALLOCATOR_FQDN from environment: {allocator_fqdn}")
        return allocator_fqdn, protocol

    # Priority 2: Build from DNS configuration
    # Determine protocol based on SSL provider
    if hasattr(cfg, "ssl") and cfg.ssl.provider != "none":
        protocol = "https"
    else:
        protocol = "http"

    # Determine host based on DNS configuration
    if hasattr(cfg, "dns") and cfg.dns.enabled and cfg.dns.domain:
        # Use DNS domain directly (now includes full domain)
        host = cfg.dns.domain

        # Remove leading dots if present (safety check)
        if host.startswith("."):
            host = host[1:]
            logger.warning(f"Removed leading dot from domain: {host}")

        logger.info(f"Using domain from config: {host}")
    else:
        # Priority 3: Use IP address
        host = allocator_ip
        logger.info(f"Using IP-only mode: {host}")

    base_url = f"{protocol}://{host}"

    return base_url, protocol


def should_use_dns(cfg) -> bool:
    """Check if DNS is enabled in config."""
    return hasattr(cfg, "dns") and cfg.dns.enabled


def should_use_https(cfg) -> bool:
    """Check if HTTPS is enabled in config."""
    return hasattr(cfg, "ssl") and cfg.ssl.provider != "none"
