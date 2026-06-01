"""When render_compose_dir saves config.yaml, plaintext admin_password
must NOT land on disk — only the argon2 hash should."""
from __future__ import annotations

import yaml
from pathlib import Path
import argon2
import pytest

from lablink_cli.commands.deploy_compose import render_compose_dir
from lablink_allocator_service.conf.structured_config import Config


@pytest.fixture
def cfg_with_plaintext_password():
    cfg = Config()
    cfg.app.admin_user = "admin"
    cfg.app.admin_password = "test-plaintext"
    cfg.app.admin_password_hash = ""
    # Fill in allocator image_tag (required by _allocator_image)
    cfg.allocator.image_tag = "linux-amd64-latest"
    return cfg


def test_render_compose_dir_hashes_admin_password(cfg_with_plaintext_password, tmp_path):
    """Plaintext admin_password must NOT appear in the saved config.yaml."""
    render_compose_dir(cfg_with_plaintext_password, tmp_path)
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text())
    # Plaintext must NOT appear in the file
    assert saved["app"].get("admin_password", "") == ""
    # Hash must appear and verify against the original plaintext
    hashed = saved["app"]["admin_password_hash"]
    assert hashed  # Hash is not empty
    # Verify the hash is valid
    argon2.PasswordHasher().verify(hashed, "test-plaintext")


def test_render_compose_dir_idempotent_on_already_hashed(tmp_path):
    """If admin_password_hash is already set, don't re-hash."""
    cfg = Config()
    cfg.app.admin_user = "admin"
    pre_hash = argon2.PasswordHasher().hash("preset")
    cfg.app.admin_password_hash = pre_hash
    cfg.app.admin_password = ""  # legacy field already empty
    cfg.allocator.image_tag = "linux-amd64-latest"
    render_compose_dir(cfg, tmp_path)
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert saved["app"]["admin_password_hash"] == pre_hash


def test_render_compose_dir_no_op_empty_password(tmp_path):
    """If both admin_password and admin_password_hash are empty, save as-is."""
    cfg = Config()
    cfg.app.admin_user = "admin"
    cfg.app.admin_password = ""
    cfg.app.admin_password_hash = ""
    cfg.allocator.image_tag = "linux-amd64-latest"
    render_compose_dir(cfg, tmp_path)
    saved = yaml.safe_load((tmp_path / "config.yaml").read_text())
    # Both fields should remain empty
    assert saved["app"].get("admin_password", "") == ""
    assert saved["app"].get("admin_password_hash", "") == ""


def test_render_compose_dir_plaintext_cleared_after_hash(cfg_with_plaintext_password):
    """After hashing, the plaintext admin_password field is cleared."""
    # Before render_compose_dir, plaintext is set
    assert cfg_with_plaintext_password.app.admin_password == "test-plaintext"
    assert cfg_with_plaintext_password.app.admin_password_hash == ""

    # After render_compose_dir, the config object has been mutated
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        render_compose_dir(cfg_with_plaintext_password, Path(tmp))
        # The plaintext should be cleared and hash should be set
        assert cfg_with_plaintext_password.app.admin_password == ""
        assert cfg_with_plaintext_password.app.admin_password_hash != ""
