"""Tests for argon2 secret hashing helper."""
from lablink_allocator_service.secret_hash import hash_secret, verify_secret


def test_hash_is_not_plaintext_and_verifies():
    h = hash_secret("tk_topsecret")
    assert h != "tk_topsecret"
    assert h.startswith("$argon2")
    assert verify_secret("tk_topsecret", h) is True


def test_wrong_secret_rejected():
    h = hash_secret("tk_topsecret")
    assert verify_secret("tk_wrong", h) is False


def test_hash_is_salted_unique():
    assert hash_secret("same") != hash_secret("same")


def test_verify_handles_garbage_hash():
    assert verify_secret("anything", "not-a-real-hash") is False
