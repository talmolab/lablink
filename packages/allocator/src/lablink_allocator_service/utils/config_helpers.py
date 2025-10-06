"""Configuration helper functions for building URLs and determining settings."""

from typing import Tuple


def get_allocator_url(cfg, allocator_ip: str) -> Tuple[str, str]:
    """
    Build the allocator URL based on configuration.

    Automatically determines the correct URL based on DNS and SSL settings.

    Args:
        cfg: Hydra configuration object
        allocator_ip: Public IP address of allocator

    Returns:
        Tuple of (base_url, protocol)

    Examples:
        DNS enabled + Let's Encrypt SSL (production):
            ("https://test.lablink.sleap.ai", "https")

        DNS enabled + Let's Encrypt SSL (staging):
            ("http://test.lablink.sleap.ai", "http")

        DNS disabled + No SSL:
            ("http://52.40.142.146", "http")

        DNS enabled + No SSL:
            ("http://test.lablink.sleap.ai", "http")

        DNS enabled + Cloudflare SSL:
            ("https://test.lablink.sleap.ai", "https")
    """
    # Determine protocol based on SSL provider
    # When staging=true, Caddy serves HTTP only (no SSL certificates)
    # When staging=false, Caddy serves HTTPS with trusted Let's Encrypt certs
    if hasattr(cfg, "ssl") and cfg.ssl.provider != "none":
        is_staging = hasattr(cfg.ssl, "staging") and cfg.ssl.staging
        if is_staging:
            # Staging mode: HTTP only
            protocol = "http"
        else:
            # Production mode: HTTPS with trusted certificates
            protocol = "https"
    else:
        protocol = "http"

    # Determine host based on DNS configuration
    if hasattr(cfg, "dns") and cfg.dns.enabled:
        # Use DNS hostname
        if cfg.dns.pattern == "custom":
            # Only add subdomain if it's non-empty
            if cfg.dns.custom_subdomain:
                host = f"{cfg.dns.custom_subdomain}.{cfg.dns.domain}"
            else:
                host = cfg.dns.domain
        elif cfg.dns.pattern == "auto":
            # For auto pattern, would need environment/resource_suffix
            # For now, fall back to custom_subdomain if available
            if cfg.dns.custom_subdomain:
                host = f"{cfg.dns.custom_subdomain}.{cfg.dns.domain}"
            else:
                host = cfg.dns.domain
        else:
            # Default to just the domain
            host = cfg.dns.domain
    else:
        # Use IP address
        host = allocator_ip

    base_url = f"{protocol}://{host}"
    return base_url, protocol


def should_use_dns(cfg) -> bool:
    """Check if DNS is enabled in config."""
    return hasattr(cfg, "dns") and cfg.dns.enabled


def should_use_https(cfg) -> bool:
    """Check if HTTPS is enabled in config."""
    return hasattr(cfg, "ssl") and cfg.ssl.provider != "none"
