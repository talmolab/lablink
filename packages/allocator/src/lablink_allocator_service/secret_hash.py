"""Argon2 hashing for at-rest deployment/client secrets (SR-F14)."""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

_ph = PasswordHasher()


def hash_secret(plaintext: str) -> str:
    """Return an argon2 hash string for `plaintext` (salted, unique per call)."""
    return _ph.hash(plaintext)


def verify_secret(plaintext: str, hashed: str) -> bool:
    """True iff `plaintext` matches `hashed`. False on any mismatch or
    malformed hash (never raises)."""
    try:
        return _ph.verify(hashed, plaintext)
    except (VerifyMismatchError, VerificationError, InvalidHashError, TypeError):
        return False
