"""Configuration helper functions for building URLs and determining settings."""

import os
import logging
from typing import Tuple

from omegaconf import DictConfig

logger = logging.getLogger(__name__)


def get_allocator_url(cfg: DictConfig, allocator_ip: str) -> Tuple[str, str]:
    """
    Build the allocator URL based on configuration.

    Priority order:
    1. ALLOCATOR_FQDN environment variable (set by Terraform)
    2. DNS configuration from config
    3. IP address fallback

    Args:
        cfg: Hydra/OmegaConf configuration object.
        allocator_ip: Public IP address of allocator.

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


def should_use_https(cfg) -> bool:
    """Check if HTTPS is enabled in config."""
    return hasattr(cfg, "ssl") and cfg.ssl.provider != "none"


# Written by the CLI (`lablink deploy`) once it has confirmed the real public
# URL via `tailscale funnel status`. Lives alongside config.yaml in the
# allocator's mounted config dir; absent on every deployment that isn't
# Funnel-exposed.
CANONICAL_URL_FILENAME = "allocator-url"


def canonical_base_url(request) -> str:
    """Return the allocator's public base URL, without a trailing slash.

    Prefers the operator-supplied canonical URL file over ``request.host_url``.
    Behind Tailscale Funnel, ``host_url`` reports ``http://`` even for requests
    that arrived over Funnel's HTTPS: manual-provider deployments only support
    ``ssl.provider: none``, so :func:`should_use_https` is false and the
    ``X-Forwarded-Proto`` gate stays shut — and Funnel does not inject that
    header anyway, so there is no in-request signal to detect it. Clients that
    take the resulting ``http://`` URL at face value only get a 302 from
    Funnel, which downgrades their POSTs to GET and surfaces as 405s.

    The file is read per request rather than cached, because the CLI writes it
    *after* `docker compose up` (Funnel can only be enabled once the container
    is running), and the allocator must pick it up without a restart.

    Falls back to ``request.host_url`` when the file is missing, empty, or does
    not contain an http(s) URL — so the AWS/nginx topology, where ProxyFix
    already yields the right scheme, is completely unaffected.
    """
    config_dir = os.getenv("CONFIG_DIR", "/config")
    path = os.path.join(config_dir, CANONICAL_URL_FILENAME)
    try:
        with open(path) as f:
            candidate = f.read().strip()
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError, PermissionError):
        candidate = ""
    except OSError as exc:  # pragma: no cover - defensive
        logger.warning("Could not read %s: %s", path, exc)
        candidate = ""

    if candidate.startswith(("http://", "https://")):
        return candidate.rstrip("/")
    if candidate:
        logger.warning(
            "Ignoring %s: %r is not an http(s) URL; falling back to request host",
            path,
            candidate,
        )
    return request.host_url.rstrip("/")


def is_self_signed_ssl(cfg) -> bool:
    """Check if the deployment uses a self-signed TLS cert.

    Used by BYO onboarding to decide whether the rendered
    ``lablink client register`` command should include ``--insecure``.
    """
    return hasattr(cfg, "ssl") and cfg.ssl.provider == "self_signed"
