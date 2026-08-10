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
SECRET_HASH_POSITIVE_TTL_S = 60.0
SECRET_HASH_NEGATIVE_TTL_S = 30.0
# Working set is the number of registered VMs (tens). Cap well above
# that so legitimate workloads never evict; the cap bounds memory under
# unique-key floods.
SECRET_HASH_CACHE_MAX_SIZE = 1024


class TtlLruCache:
    """Thread-safe TTL + LRU cache with an optional per-key version guard.

    Both caches in this module are instances of this: the
    client_secret_hash cache (keyed by hostname, distinct positive and
    negative TTLs, version guard in use — see
    ``VmDatabase.get_client_secret_hash``) and the verify-result cache
    (keyed by ``(subject, token-fingerprint)``, successes only, no
    version guard).

    ``negative_ttl`` applies to a stored ``None`` and defaults to
    ``ttl``. The secret-hash cache sets it shorter so a freshly
    registered host becomes auth-able within seconds without a
    register-time invalidate, and so a repeatedly probed unknown
    hostname doesn't linger.

    Race-against-rotation: :meth:`get` returns a per-key version token
    that :meth:`put` re-checks under the lock. If :meth:`invalidate` ran
    in between — a concurrent ``register_client`` rotating the secret
    while a stale SELECT was in flight — the mismatch rejects the stale
    write, so the next call re-queries and picks up the new value. Pass
    ``expected_version=None`` to skip the check; the verify cache has
    nothing to race with, since it stores a result it derived itself
    rather than a value it fetched.

    Bounded size: an ``OrderedDict`` with LRU eviction on insert beyond
    ``max_size``. Both ``get`` and ``put`` move the entry to the
    most-recently-used end. The bound is a DoS guard against unique-key
    floods, not a working-set sizing knob.
    """

    def __init__(
        self,
        *,
        ttl: float,
        max_size: int,
        negative_ttl: float | None = None,
    ):
        if max_size < 1:
            raise ValueError(f"Invalid cache max_size: {max_size}")
        self._ttl = ttl
        self._negative_ttl = ttl if negative_ttl is None else negative_ttl
        self._max_size = max_size
        self._lock = threading.RLock()
        # key -> (value, expires_at) on the monotonic clock
        self._entries: OrderedDict = OrderedDict()
        # key -> int. Bumped only by invalidate(); never reset by TTL
        # expiry or LRU eviction (those aren't "the value changed"
        # events). put() rejects stores whose observed version is stale.
        self._versions: dict = {}

    def get(self, key):
        """Return ``(hit, value, version)``.

        ``hit=False`` means the caller must re-fetch; pass ``version``
        back to :meth:`put` so a concurrent invalidate between get and
        put rejects the stale write.
        """
        with self._lock:
            version = self._versions.get(key, 0)
            entry = self._entries.get(key)
            if entry is None:
                return False, None, version
            value, expires_at = entry
            if time.monotonic() >= expires_at:
                del self._entries[key]
                return False, None, version
            # LRU touch
            self._entries.move_to_end(key)
            return True, value, version

    def put(self, key, value, expected_version: int | None = None) -> bool:
        """Store ``value`` for ``key`` if no invalidate raced.

        Returns ``True`` if the entry was written, ``False`` if a
        concurrent :meth:`invalidate` bumped the version between the
        caller's :meth:`get` and this ``put``.
        """
        ttl = self._ttl if value is not None else self._negative_ttl
        with self._lock:
            if (
                expected_version is not None
                and self._versions.get(key, 0) != expected_version
            ):
                return False
            self._entries[key] = (value, time.monotonic() + ttl)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_size:
                self._entries.popitem(last=False)
            return True

    def invalidate(self, key) -> None:
        with self._lock:
            self._versions[key] = self._versions.get(key, 0) + 1
            self._entries.pop(key, None)

    def invalidate_where(self, predicate) -> None:
        """Drop every entry whose key satisfies ``predicate``.

        Unlike :meth:`invalidate` this bumps no version — it exists for
        the verify cache, whose compound key means one subject owns an
        unbounded set of keys and which runs no version guard anyway.
        """
        with self._lock:
            for key in [k for k in self._entries if predicate(k)]:
                del self._entries[key]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._versions.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_verify_cache = TtlLruCache(
    ttl=_VERIFY_RESULT_POSITIVE_TTL_S,
    max_size=_VERIFY_RESULT_CACHE_MAX_SIZE,
)


def verify_secret_cached(subject: str, plaintext: str, hashed: str) -> bool:
    """Same contract as :func:`verify_secret` but memoizes successes by
    ``(subject, sha256(plaintext))`` for ~60 s.

    The first call pays the argon2 verify cost; subsequent calls with
    the same ``(subject, plaintext)`` within the TTL return True without
    running argon2. Failures are never cached, so a wrong token always
    pays the verify cost — there's no fast path for attackers, and a
    wrong token cannot poison an entry either: it has a different
    fingerprint, so it lands on a different key.

    Use a ``subject`` the caller has already identified out-of-band
    (e.g., hostname from the request body, client_id from the URL), so
    a cache hit doesn't silently accept a token across identities.
    """
    key = (subject, _token_fingerprint(plaintext))
    hit, _, _ = _verify_cache.get(key)
    if hit:
        return True
    if verify_secret(plaintext, hashed):
        _verify_cache.put(key, True)
        return True
    return False


def invalidate_verify(subject: str) -> None:
    """Drop every cached verify result for ``subject``.

    Call whenever the stored hash for a subject changes — e.g., on
    ``register_client`` (rotation) or ``unregister_client`` (removal),
    the same hook the secret-hash cache uses, so a rotated secret does
    not keep accepting old tokens up to the TTL.
    """
    _verify_cache.invalidate_where(lambda k: k[0] == subject)


def clear_verify_cache() -> None:
    """Test helper: drop every cached entry."""
    _verify_cache.clear()
