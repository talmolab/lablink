"""Argon2 hashing for at-rest deployment/client secrets (SR-F14)."""
from __future__ import annotations

import hashlib
import threading
import time
from collections import OrderedDict

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


# Verify-result cache. argon2 verify is intentionally CPU-heavy
# (~50-200 ms per call) and every authed allocator endpoint runs it.
# During a 30-VM launch burst that's tens of seconds of CPU stacked up
# behind the Flask dev-server's GIL, which is why the admin UI feels
# slow for the first 1-2 minutes. Caching the *result* of verify()
# means each (subject, token) pair only pays the argon2 cost once per
# TTL — first verify warms the cache, the remaining ~10-15 polls from
# the same VM during the burst skip argon2 entirely.
_VERIFY_RESULT_POSITIVE_TTL_S = 60.0
# Working set is one entry per active client VM plus the register-token
# sentinel; cap well above that. Bound is a DoS guard, not a sizing knob.
_VERIFY_RESULT_CACHE_MAX_SIZE = 1024

# Sentinel subject for the deployment-wide register_token. The token is
# shared across all client registrations and isn't tied to any single
# hostname, so it gets its own cache namespace.
REGISTER_TOKEN_SUBJECT = "__register_token__"


def _token_fingerprint(plaintext: str) -> str:
    """Stable, fixed-length key derived from the plaintext token.

    sha256 keeps the plaintext token out of the cache's key set (defense
    in depth against in-memory inspection) and gives the dict lookup a
    fixed-size key regardless of token length.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


# Secret-hash cache sizing. Every authed allocator endpoint reads the
# argon2 hash before letting the request through. With ~30 client VMs
# polling on tight loops the lookup alone can starve the pool during
# bursts. The cache is invalidated by register_client and
# unregister_client; TTLs are a safety net for any unexpected writer.
# Positive TTL is short (60 s) so that any path that updates the hash
# without going through invalidate (e.g. direct SQL, future code) only
# leaves stale auth state for ~1 minute. With ~30 VMs polling at ~1 Hz
# this still cuts steady-state DB load by ~60×.
_SECRET_HASH_POSITIVE_TTL_S = 60.0
_SECRET_HASH_NEGATIVE_TTL_S = 30.0
# Working set is the number of registered VMs (tens). Cap well above
# that so legitimate workloads never evict; the cap bounds memory under
# unique-key floods.
_SECRET_HASH_CACHE_MAX_SIZE = 1024


class SecretHashCache:
    """Thread-safe per-hostname TTL+LRU cache for client_secret_hash.

    Caches both real hashes (positive_ttl) and absent-hostname None
    results (negative_ttl). The shorter negative TTL keeps freshly
    registered hosts auth-able within seconds without a register-time
    invalidate, and limits how long a repeatedly probed unknown
    hostname sits in memory.

    Race-against-rotation: ``get`` returns a per-hostname version token
    that ``put`` re-checks under lock. If ``invalidate`` ran between
    ``get`` and ``put`` — i.e. a concurrent ``register_client`` rotated
    the secret while a stale SELECT was in flight — the version
    mismatch rejects the stale write, so the next call re-queries the
    DB and picks up the new hash.

    Bounded size: the underlying store is an ``OrderedDict`` with LRU
    eviction on insert beyond ``max_size``. Both ``get`` and ``put``
    move the entry to the most-recently-used end. This bounds memory
    even if a misbehaving caller iterates through unique fake
    hostnames.
    """

    def __init__(
        self,
        *,
        positive_ttl_seconds: float = _SECRET_HASH_POSITIVE_TTL_S,
        negative_ttl_seconds: float = _SECRET_HASH_NEGATIVE_TTL_S,
        max_size: int = _SECRET_HASH_CACHE_MAX_SIZE,
    ):
        if max_size < 1:
            raise ValueError(f"Invalid cache max_size: {max_size}")
        self._positive_ttl = positive_ttl_seconds
        self._negative_ttl = negative_ttl_seconds
        self._max_size = max_size
        self._lock = threading.RLock()
        # hostname -> (value, expires_at)
        self._entries: OrderedDict = OrderedDict()
        # hostname -> int. Bumped only by invalidate(); never reset by
        # TTL expiry or LRU eviction (those aren't "the hash changed"
        # events). put() rejects stores whose observed version is stale.
        self._versions: dict = {}

    def get(self, hostname: str):
        """Return ``(hit, value, version)``.

        ``hit=False`` means the caller must query the DB; pass
        ``version`` back to :meth:`put` so a concurrent invalidate
        between get and put rejects the stale write.
        """
        with self._lock:
            version = self._versions.get(hostname, 0)
            entry = self._entries.get(hostname)
            if entry is None:
                return False, None, version
            value, expires_at = entry
            if time.monotonic() >= expires_at:
                del self._entries[hostname]
                return False, None, version
            # LRU touch
            self._entries.move_to_end(hostname)
            return True, value, version

    def put(self, hostname: str, value, expected_version: int) -> bool:
        """Store ``value`` for ``hostname`` if no invalidate raced.

        Returns ``True`` if the entry was written, ``False`` if a
        concurrent ``invalidate`` bumped the version between the
        caller's ``get`` and this ``put``.
        """
        ttl = self._positive_ttl if value is not None else self._negative_ttl
        with self._lock:
            if self._versions.get(hostname, 0) != expected_version:
                return False
            self._entries[hostname] = (value, time.monotonic() + ttl)
            self._entries.move_to_end(hostname)
            # Evict LRU entries beyond cap. Bound is a soft DoS guard,
            # not a working-set sizing knob.
            while len(self._entries) > self._max_size:
                self._entries.popitem(last=False)
            return True

    def invalidate(self, hostname: str) -> None:
        with self._lock:
            self._versions[hostname] = self._versions.get(hostname, 0) + 1
            self._entries.pop(hostname, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._versions.clear()


class _VerifyResultCache:
    """Thread-safe per-(subject, token-fingerprint) TTL+LRU cache for
    successful argon2 verifies.

    Only successes are cached. A failed verify is never written, so a
    wrong token can't poison entries: it would have a different
    fingerprint and would still pay the full argon2 cost.

    Invalidation: ``invalidate(subject)`` drops every entry for that
    subject. Called from the registration paths that rotate or remove a
    stored hash (the same hook ``SecretHashCache`` uses), so a rotated
    secret doesn't keep accepting old tokens up to the TTL.

    Bounded size: OrderedDict with LRU eviction on insert beyond
    ``max_size``. Bound is a DoS guard against unique-key floods.
    """

    def __init__(
        self,
        *,
        positive_ttl_seconds: float = _VERIFY_RESULT_POSITIVE_TTL_S,
        max_size: int = _VERIFY_RESULT_CACHE_MAX_SIZE,
    ):
        if max_size < 1:
            raise ValueError(f"Invalid cache max_size: {max_size}")
        self._positive_ttl = positive_ttl_seconds
        self._max_size = max_size
        self._lock = threading.RLock()
        # (subject, token_fp) -> expires_at (monotonic seconds)
        self._entries: OrderedDict = OrderedDict()

    def is_verified(self, subject: str, token_fp: str) -> bool:
        key = (subject, token_fp)
        with self._lock:
            expires_at = self._entries.get(key)
            if expires_at is None:
                return False
            if time.monotonic() >= expires_at:
                del self._entries[key]
                return False
            self._entries.move_to_end(key)
            return True

    def mark_verified(self, subject: str, token_fp: str) -> None:
        key = (subject, token_fp)
        with self._lock:
            self._entries[key] = time.monotonic() + self._positive_ttl
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_size:
                self._entries.popitem(last=False)

    def invalidate(self, subject: str) -> None:
        with self._lock:
            keys_to_drop = [k for k in self._entries if k[0] == subject]
            for k in keys_to_drop:
                del self._entries[k]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_verify_cache = _VerifyResultCache()


def verify_secret_cached(subject: str, plaintext: str, hashed: str) -> bool:
    """Same contract as :func:`verify_secret` but memoizes successes by
    ``(subject, sha256(plaintext))`` for ~60 s.

    The first call pays the argon2 verify cost; subsequent calls with
    the same ``(subject, plaintext)`` within the TTL return True without
    running argon2. Failures are never cached, so a wrong token always
    pays the verify cost — there's no fast path for attackers.

    Use a ``subject`` the caller has already identified out-of-band
    (e.g., hostname from the request body, client_id from the URL), so
    a cache hit doesn't silently accept a token across identities.
    """
    fp = _token_fingerprint(plaintext)
    if _verify_cache.is_verified(subject, fp):
        return True
    if verify_secret(plaintext, hashed):
        _verify_cache.mark_verified(subject, fp)
        return True
    return False


def invalidate_verify(subject: str) -> None:
    """Drop every cached verify result for ``subject``.

    Call whenever the stored hash for a subject changes — e.g., on
    ``register_client`` (rotation) or ``unregister_client`` (removal).
    """
    _verify_cache.invalidate(subject)


def clear_verify_cache() -> None:
    """Test helper: drop every cached entry."""
    _verify_cache.clear()
