"""Config validation CLI for LabLink Allocator Service.

This module provides a command-line tool to validate configuration files
against the Hydra/OmegaConf schema before deployment. This enables fail-fast
validation during CI/CD pipelines.
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import Tuple

from hydra.errors import ConfigCompositionException
from omegaconf import DictConfig
from omegaconf.errors import ConfigKeyError, ValidationError

from lablink_allocator_service.conf.structured_config import MISSING_SECRET
from lablink_allocator_service.get_config import get_config

logger = logging.getLogger(__name__)

# Top-level provider field — must stay in sync with the providers registry
# (DEFAULT_PROVIDER / get_provider). "manual" is the BYO-clients mode added
# in PR D1/D2/D3 — no automated provisioning, clients self-register via the
# `lablink client register` CLI.
VALID_PROVIDERS = ("aws", "manual")

# manual.connectivity — must stay in sync with the connectivity registry
# (_CONNECTIVITY_BUILTIN in providers/registry.py). "mesh_overlay" reaches
# clients that aren't on the allocator's own LAN over a Tailscale tailnet;
# "relay" reaches them over an frp tunnel the client dials out through,
# for networks that won't carry Tailscale at all.
VALID_CONNECTIVITY = ("lan_direct", "mesh_overlay", "relay")

# manual.participant_exposure — how participants (not clients) reach the
# allocator when it isn't on their LAN. Independent of connectivity above;
# "tailscale_funnel" reuses the same tailnet, just for a different purpose
# (publishing the allocator's own HTTP port, not reaching a client).
VALID_PARTICIPANT_EXPOSURE = ("none", "tailscale_funnel")

# Deployment-example / commonly-typed weak values a Funnel-exposed admin
# panel must never ship with — CT-log scanning finds a newly-published
# Funnel host within minutes of publication (empirically confirmed
# 2026-07-22), so "my own LAN, who cares" stops being a defensible posture
# the moment participant_exposure != "none". "placeholder_admin_password"
# is included despite exceeding MIN_ADMIN_PASSWORD_LENGTH: it's the literal
# value committed in conf/config.yaml (meant to be injected from a GitHub
# secret at AWS deploy time) — publicly known simply by being in this
# repo, so a manual config that retained it unchanged is exactly as
# compromised as one using "123456".
WEAK_ADMIN_PASSWORDS = frozenset(
    {"123456", "admin", "password", "changeme", "placeholder_admin_password", ""}
)
MIN_ADMIN_PASSWORD_LENGTH = 12


def is_weak_admin_password(password: str) -> bool:
    """True if *password* is empty, a known example/default value, or
    shorter than the minimum length required once the allocator is
    reachable from the public internet."""
    if not password:
        return True
    if password.lower() in WEAK_ADMIN_PASSWORDS:
        return True
    return len(password) < MIN_ADMIN_PASSWORD_LENGTH


# frps's control port is reachable from client networks by construction
# (that is the whole point of relay connectivity), so it is exposed to the
# same CT-log-driven scanning as a Funnel-published admin panel. The design
# spec's Error Handling section is explicit: don't ship this with a weak
# default. Kept separate from WEAK_ADMIN_PASSWORDS because an frp control
# token is machine-generated and can afford a longer minimum than a
# human-typed password.
WEAK_FRPS_TOKENS = frozenset(
    {"", "token", "secret", "changeme", "password", "frp", "frps", "lablink", "test"}
)
MIN_FRPS_TOKEN_LENGTH = 16


def is_weak_frps_token(token: str) -> bool:
    """True if *token* is empty, a known example/default value, or shorter
    than the minimum length required of a token guarding a port that is
    reachable from outside the allocator's own network."""
    if not token:
        return True
    if token.lower() in WEAK_FRPS_TOKENS:
        return True
    return len(token) < MIN_FRPS_TOKEN_LENGTH


def validate_domain_format(domain: str) -> Tuple[bool, str]:
    """Validate domain format to prevent malformed domains.

    Args:
        domain: Domain name to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not domain:
        return True, ""  # Empty is allowed when DNS disabled

    # Check for leading/trailing dots
    if domain.startswith("."):
        return False, "Domain cannot start with a dot"
    if domain.endswith("."):
        return False, "Domain cannot end with a dot"

    return True, ""


def get_config_errors(cfg) -> list:
    """Return a list of DNS/SSL validation errors (empty = valid).

    This is the single source of truth for DNS/SSL validation rules,
    shared by both the allocator's validate_config CLI and the
    lablink CLI's config validation.

    Args:
        cfg: Any config object with .dns and .ssl attributes
            (works with both Config dataclass and DictConfig).

    Returns:
        List of error message strings.
    """
    errors = []

    # Top-level provider must be one of the registered providers.
    # `getattr` keeps the validator robust if a legacy DictConfig without
    # the `provider` field is passed in (defaults to the registry default).
    provider = getattr(cfg, "provider", "aws")
    if provider not in VALID_PROVIDERS:
        errors.append(
            f"provider must be one of: {', '.join(VALID_PROVIDERS)} (got '{provider}')"
        )

    # manual.connectivity must be a known value. Either mesh_overlay
    # (to resolve overlay hostnames — see
    # MeshOverlayClientConnectivity._resolve_overlay_host) or
    # participant_exposure == "tailscale_funnel" (to publish the
    # allocator's own hostname) requires a tailnet domain.
    manual_cfg = getattr(cfg, "manual", None)
    if manual_cfg is not None:
        connectivity = getattr(manual_cfg, "connectivity", "lan_direct")
        if connectivity not in VALID_CONNECTIVITY:
            errors.append(
                f"manual.connectivity must be one of: "
                f"{', '.join(VALID_CONNECTIVITY)} (got '{connectivity}')"
            )

        participant_exposure = getattr(manual_cfg, "participant_exposure", "none")
        if participant_exposure not in VALID_PARTICIPANT_EXPOSURE:
            errors.append(
                f"manual.participant_exposure must be one of: "
                f"{', '.join(VALID_PARTICIPANT_EXPOSURE)} "
                f"(got '{participant_exposure}')"
            )

        # lan_direct sends the participant's browser straight to a client's
        # LAN IP (ws://<client-ip>:6080 — see LANDirectClientConnectivity),
        # bypassing the allocator entirely. That's unreachable off-LAN and,
        # once the allocator itself is Funnel-exposed, actively blocked as
        # mixed content by the browser (ws:// from an https:// page).
        # mesh_overlay doesn't have this problem — it proxies sessions
        # through the allocator's own nginx, which Funnel already exposes.
        if participant_exposure == "tailscale_funnel" and connectivity == "lan_direct":
            errors.append(
                "manual.participant_exposure is 'tailscale_funnel' but "
                "manual.connectivity is 'lan_direct' — participant sessions "
                "would connect directly to a client's LAN IP, which is "
                "unreachable off-LAN and blocked as mixed content from the "
                "HTTPS Funnel page. Use manual.connectivity: mesh_overlay "
                "instead, which proxies sessions through the allocator."
            )

        needs_tailnet = (
            connectivity == "mesh_overlay" or participant_exposure == "tailscale_funnel"
        )
        if needs_tailnet and not getattr(manual_cfg, "overlay_tailnet", ""):
            errors.append(
                "manual.overlay_tailnet is required when manual.connectivity "
                "is 'mesh_overlay' or manual.participant_exposure is "
                "'tailscale_funnel' (e.g. 'example.ts.net')"
            )

        # relay's two load-bearing config values. Checked at validation
        # time rather than at first registration: without relay_server_addr,
        # register_client's rpartition(":") yields an empty host and
        # int("") raises, turning a misconfiguration into a 500 on the
        # first client to register instead of a startup error message.
        if connectivity == "relay":
            relay_addr = getattr(manual_cfg, "relay_server_addr", "")
            if not relay_addr:
                errors.append(
                    "manual.relay_server_addr is required when "
                    "manual.connectivity is 'relay' — relay clients' frpc "
                    "dial this host:port to reach the allocator's frps "
                    "(e.g. 'allocator.example.com:7000')"
                )
            else:
                # Must be parseable by register_client's
                # `relay_server_addr.rpartition(":")` + `int(port)`, or the
                # first relay registration 500s instead of failing here.
                # rpartition (not partition) is what makes bracketed IPv6
                # like "[::1]:7000" split correctly.
                host, sep, port = relay_addr.rpartition(":")
                if not sep or not host or not port.isdigit() or not (
                    1 <= int(port) <= 65535
                ):
                    errors.append(
                        "manual.relay_server_addr must be 'host:port' with a "
                        "numeric port in 1-65535 (e.g. "
                        f"'allocator.example.com:7000'); got '{relay_addr}'"
                    )
            if is_weak_frps_token(getattr(manual_cfg, "frps_auth_token", "")):
                errors.append(
                    "manual.connectivity is 'relay' but "
                    "manual.frps_auth_token is empty, a known example "
                    "value, or shorter than "
                    f"{MIN_FRPS_TOKEN_LENGTH} characters — frps's control "
                    "port is reachable from client networks and is scanned "
                    "by bots within minutes of exposure; set a strong token"
                )

        if participant_exposure == "tailscale_funnel":
            admin_password = getattr(getattr(cfg, "app", None), "admin_password", "")
            # MISSING_SECRET is AppConfig.admin_password's dataclass default —
            # the sentinel for "not yet resolved" (the wizard never collects
            # it; resolve_admin_credentials fills it in at deploy time, and
            # THAT resolved value is what deploy_compose.py's own preflight
            # gate checks). Treating the sentinel as "weak" would block
            # `lablink configure`'s ReviewScreen on every fresh config,
            # before the operator has had any chance to set a real password.
            if admin_password != MISSING_SECRET and is_weak_admin_password(
                admin_password
            ):
                errors.append(
                    "manual.participant_exposure is 'tailscale_funnel' but "
                    "app.admin_password is empty, a known example value, or "
                    "shorter than 12 characters — a Funnel-exposed allocator "
                    "is scanned by bots within minutes; set a strong "
                    "admin_password"
                )

    # DNS enabled requires non-empty domain
    if cfg.dns.enabled and not cfg.dns.domain:
        errors.append("DNS enabled requires non-empty domain field")

    # Validate domain format
    is_valid, error_msg = validate_domain_format(cfg.dns.domain)
    if not is_valid:
        errors.append(error_msg)

    # SSL (non-"none") requires DNS
    if cfg.ssl.provider != "none" and not cfg.dns.enabled:
        errors.append(
            'SSL requires DNS to be enabled (use provider="none" for HTTP-only)'
        )

    # Let's Encrypt requires email
    if cfg.ssl.provider == "letsencrypt" and not cfg.ssl.email:
        errors.append("Let's Encrypt requires email address")

    # ACM requires certificate_arn
    if cfg.ssl.provider == "acm" and not cfg.ssl.certificate_arn:
        errors.append("ACM provider requires certificate_arn")

    # CloudFlare SSL requires external DNS (terraform_managed=false)
    if cfg.ssl.provider == "cloudflare" and cfg.dns.terraform_managed:
        errors.append(
            "CloudFlare SSL requires terraform_managed=false (external DNS management)"
        )

    return errors


def validate_config_logic(cfg: DictConfig) -> Tuple[bool, str]:
    """Validate configuration logic and dependencies.

    Args:
        cfg: Loaded Hydra/OmegaConf configuration object.

    Returns:
        Tuple of (is_valid, error_message)
    """
    errors = get_config_errors(cfg)

    if errors:
        error_msg = "[FAIL] Config validation failed:\n"
        for error in errors:
            error_msg += f"       - {error}\n"
        return False, error_msg

    return True, ""


def validate_config(config_path: str) -> Tuple[bool, str]:
    """Validate a configuration file against the schema.

    Args:
        config_path: Path to the config.yaml file to validate

    Returns:
        Tuple of (is_valid, message):
            - is_valid: True if config is valid, False otherwise
            - message: Success or error message
    """
    path = Path(config_path)

    # Check if file exists
    if not path.exists():
        return False, f"[FAIL] Config file not found: {config_path}"

    if not path.is_file():
        return False, f"[FAIL] Config path is not a file: {config_path}"

    # Require config.yaml filename for Hydra schema matching
    if path.name != "config.yaml":
        return False, (
            f"[FAIL] Config file must be named 'config.yaml'\n"
            f"       Found: {path.name}\n"
            f"       Rename your file to enable strict schema validation"
        )

    try:
        # Use get_config() with explicit path - it validates automatically
        cfg = get_config(config_path=path.as_posix())

        # Run logic validation
        is_valid, error_msg = validate_config_logic(cfg)
        if not is_valid:
            return False, error_msg

        return True, "[PASS] Config validation passed"

    except ConfigCompositionException as e:
        # This is the error from your Docker logs - extract the key info
        error_msg = (
            "[FAIL] Config validation failed: Error merging config with schema\n"
        )
        error_str = str(e)

        # Try to extract the key that caused the problem
        if "Key '" in error_str and "' not in" in error_str:
            # Extract key name from error message
            key_start = error_str.find("Key '") + 5
            key_end = error_str.find("'", key_start)
            bad_key = error_str[key_start:key_end]
            error_msg += f"       Unknown key: '{bad_key}'\n"
            error_msg += "       This key is not defined in the Config schema\n"
        else:
            error_msg += f"       {error_str}\n"

        return False, error_msg

    except ConfigKeyError as e:
        error_msg = "[FAIL] Config validation failed: Unknown configuration key\n"
        error_msg += f"       Key '{e.key}' not found in schema"
        if hasattr(e, "full_key") and e.full_key:
            error_msg += f"\n       Full key path: {e.full_key}"
        if hasattr(e, "object_type") and e.object_type:
            type_name = (
                e.object_type.__name__
                if hasattr(e.object_type, "__name__")
                else str(e.object_type)
            )
            error_msg += f"\n       Expected in schema: {type_name}"
        error_msg += "\n"
        return False, error_msg

    except ValidationError as e:
        error_msg = "[FAIL] Config validation failed: Schema validation error\n"
        error_msg += f"       {str(e)}\n"
        return False, error_msg

    except Exception as e:
        logger.exception("Unexpected error during config validation")
        error_msg = f"[FAIL] Config validation failed: {type(e).__name__}\n"
        error_msg += f"       {str(e)}\n"
        return False, error_msg


def main():
    """Main entry point for the config validation CLI."""
    logging.basicConfig(
        level=logging.WARNING,
        format="%(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Validate LabLink allocator configuration file against schema",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Validate deployment config
  lablink-validate-config config/config.yaml

  # Validate runtime config in Docker
  lablink-validate-config /config/config.yaml

  # Validate bundled config
  lablink-validate-config \\
      packages/allocator/src/lablink_allocator_service/conf/config.yaml

NOTE: Config file MUST be named 'config.yaml' for schema validation.

Exit codes:
  0 - Config is valid
  1 - Config is invalid or error occurred
        """,
    )

    parser.add_argument(
        "config_path",
        nargs="?",
        default="/config/config.yaml",
        help="Path to the config.yaml file to validate (default: /config/config.yaml)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    # Set logging level based on verbosity
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)
        logging.getLogger("lablink_allocator_service").setLevel(logging.INFO)

    # Validate the configuration
    is_valid, message = validate_config(args.config_path)

    # Print the result
    print(message)

    # Exit with appropriate code
    sys.exit(0 if is_valid else 1)


if __name__ == "__main__":
    main()
