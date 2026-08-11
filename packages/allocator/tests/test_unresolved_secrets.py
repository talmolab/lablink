"""Tests for the unresolved-credential gate.

lablink-template commits config.yaml with PLACEHOLDER_* credentials and its
deploy workflow substitutes them from GitHub secrets. A local `terraform
apply` -- a documented path in that repo's README -- performs no substitution,
so the literal is baked into the instance and the allocator would otherwise
serve an admin UI whose password is published in a public template.
"""

import importlib.util
from pathlib import Path

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


def test_startup_gate_covers_every_credential_it_reads():
    """main.py gates admin_user, admin_password and db.password.

    Read via find_spec rather than by importing main.py: that module builds a
    Flask app, a DB pool and a provider at import time, and -- now that this
    gate exists -- exits on the shipped default config, which still carries
    PLACEHOLDER_* values. Importing it here would make the test pass or fail
    depending on whether another test imported it first.
    """
    origin = importlib.util.find_spec("lablink_allocator_service.main").origin
    src = Path(origin).read_text()
    gate = src.split("_missing = []", 1)[1].split("if _missing:", 1)[0]

    for field in ("cfg.app.admin_user", "cfg.app.admin_password", "cfg.db.password"):
        assert f"is_unresolved_secret({field})" in gate, field
