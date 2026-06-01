"""Tests for D5 admin_password_hash: hash field, legacy fallback, errors."""
from __future__ import annotations

import logging
import pytest
from lablink_allocator_service import secret_hash


@pytest.fixture
def app_with_hash(monkeypatch, omega_config):
    """Build a Flask test app whose admin password is set via the new hash field."""
    from lablink_allocator_service import main  # noqa: WPS433 — import for mocking

    plaintext = "correct-horse-battery-staple"
    hash_value = secret_hash.hash_secret(plaintext)

    # Patch the config to use hash field instead of plaintext
    monkeypatch.setattr(omega_config.app, "admin_password_hash", hash_value)
    monkeypatch.setattr(omega_config.app, "admin_password", "")
    monkeypatch.setattr(main, "cfg", omega_config, raising=False)

    # Re-initialize users dict after config change; monkeypatch ensures
    # the prior value is restored at test teardown so neighboring tests
    # don't observe stale state.
    monkeypatch.setattr(main, "users", main._init_users())

    return main.app, omega_config.app.admin_user, plaintext


def test_login_accepts_correct_plaintext_against_hash(app_with_hash):
    app, user, plaintext = app_with_hash
    with app.test_client() as c:
        r = c.get("/admin/instances", headers={
            "Authorization": _basic(user, plaintext),
        })
    assert r.status_code != 401


def test_login_rejects_wrong_plaintext_against_hash(app_with_hash):
    app, user, _ = app_with_hash
    with app.test_client() as c:
        r = c.get("/admin/instances", headers={
            "Authorization": _basic(user, "WRONG"),
        })
    assert r.status_code == 401


def test_legacy_plaintext_logs_deprecation_and_works(monkeypatch, caplog, omega_config):
    """Pre-D5 configs with only `admin_password` keep working, with a warning."""
    from lablink_allocator_service import main
    plaintext = "legacy-password"
    monkeypatch.setattr(omega_config.app, "admin_password_hash", "")
    monkeypatch.setattr(omega_config.app, "admin_password", plaintext)
    monkeypatch.setattr(main, "cfg", omega_config, raising=False)

    with caplog.at_level(logging.WARNING):
        main.users = main._init_users()  # helper introduced in Step 3 below

    assert any("admin_password (plaintext) is deprecated" in r.message
               for r in caplog.records)
    # Hash now lives in users dict, plaintext does not.
    assert secret_hash.verify_secret(plaintext, main.users[omega_config.app.admin_user])


def test_both_fields_set_hash_wins(monkeypatch, omega_config):
    from lablink_allocator_service import main
    monkeypatch.setattr(omega_config.app, "admin_password_hash",
                        secret_hash.hash_secret("the-real-one"))
    monkeypatch.setattr(omega_config.app, "admin_password", "ignored")
    monkeypatch.setattr(main, "cfg", omega_config, raising=False)
    main.users = main._init_users()
    assert secret_hash.verify_secret("the-real-one",
                                     main.users[omega_config.app.admin_user])
    assert not secret_hash.verify_secret("ignored",
                                         main.users[omega_config.app.admin_user])


def test_neither_field_set_fails_startup(monkeypatch, omega_config):
    from lablink_allocator_service import main
    monkeypatch.setattr(omega_config.app, "admin_password_hash", "")
    monkeypatch.setattr(omega_config.app, "admin_password", "")
    monkeypatch.setattr(main, "cfg", omega_config, raising=False)
    with pytest.raises(SystemExit) as exc:
        main._validate_admin_secrets()  # helper introduced in Step 3 below
    assert "admin_password" in str(exc.value)


def _basic(user: str, password: str) -> str:
    import base64
    raw = f"{user}:{password}".encode()
    return "Basic " + base64.b64encode(raw).decode()
