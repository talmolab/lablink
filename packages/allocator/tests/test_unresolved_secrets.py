"""Tests for the unresolved-credential gate.

lablink-template commits config.yaml with PLACEHOLDER_* credentials and its
deploy workflow substitutes them from GitHub secrets. A local `terraform
apply` -- a documented path in that repo's README -- performs no substitution,
so the literal is baked into the instance and the allocator would otherwise
serve an admin UI whose password is published in a public template.
"""

import subprocess
import sys

import pytest

from lablink_allocator_service.conf.structured_config import (
    MISSING_SECRET,
    is_unresolved_secret,
)
from lablink_allocator_service.validate_config import validate_config


@pytest.mark.parametrize(
    "value",
    [
        MISSING_SECRET,
        "PLACEHOLDER_ADMIN_PASSWORD",
        "PLACEHOLDER_DB_PASSWORD",
        "PLACEHOLDER_SOMETHING_ADDED_LATER",
    ],
)
def test_sentinels_are_unresolved(value):
    assert is_unresolved_secret(value) is True


@pytest.mark.parametrize(
    "value",
    [
        "test_admin_password",
        "lablink",
        "",
        # Substrings and lowercase must not trip the prefix match; only a
        # credential that literally starts with the sentinel is unfilled.
        "placeholder_admin_password",
        "my-PLACEHOLDER_password",
    ],
)
def test_real_credentials_are_resolved(value):
    assert is_unresolved_secret(value) is False


def test_config_validation_still_accepts_placeholders(
    valid_config_dict, write_config_file
):
    """The template's committed config must keep passing config-time validation.

    The deploy workflow validates config.yaml *before* substituting the
    sentinels, so placeholders are legitimate at that point. Rejecting them
    there would fail every template deployment; the gate belongs at allocator
    startup, after substitution has had its chance. This test is the guard
    against someone "fixing" the problem in the wrong layer.
    """
    valid_config_dict["app"]["admin_password"] = "PLACEHOLDER_ADMIN_PASSWORD"
    valid_config_dict["db"]["password"] = "PLACEHOLDER_DB_PASSWORD"

    is_valid, message = validate_config(write_config_file(valid_config_dict))

    assert is_valid is True, message


@pytest.mark.parametrize(
    "field", ["app.admin_user", "app.admin_password", "db.password"]
)
def test_startup_gate_covers_every_credential_it_reads(field, monkeypatch, app):
    """Startup refuses when any one of the three credentials is a sentinel."""
    from omegaconf import OmegaConf

    from lablink_allocator_service import main

    section, key = field.split(".")
    cfg = OmegaConf.create(OmegaConf.to_container(main.cfg, resolve=True))
    cfg[section][key] = "PLACEHOLDER_UNFILLED"
    monkeypatch.setattr(main, "cfg", cfg)

    with pytest.raises(SystemExit, match=field):
        main.verify_secrets_resolved()


def test_startup_gate_passes_on_real_credentials(app):
    """The test config carries real values, so startup must not be blocked."""
    from lablink_allocator_service import main

    main.verify_secrets_resolved()


def test_importing_main_does_not_run_the_gate():
    """The gate belongs in main(), not at import.

    The shipped config.yaml legitimately holds PLACEHOLDER_* values, so a gate
    at module scope makes `import lablink_allocator_service.main` exit 1 --
    which is exactly what the image-verification CI job does.
    """
    result = subprocess.run(
        [sys.executable, "-c", "import lablink_allocator_service.main"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
