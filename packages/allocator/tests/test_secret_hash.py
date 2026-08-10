"""Tests for argon2 secret hashing helper and verify-result cache."""
from unittest.mock import patch

import pytest

from lablink_allocator_service import secret_hash
from lablink_allocator_service.secret_hash import (
    REGISTER_TOKEN_SUBJECT,
    SECRET_HASH_CACHE_MAX_SIZE,
    SECRET_HASH_NEGATIVE_TTL_S,
    SECRET_HASH_POSITIVE_TTL_S,
    TtlLruCache,
    _token_fingerprint,
    clear_verify_cache,
    hash_secret,
    invalidate_verify,
    verify_secret,
    verify_secret_cached,
)


@pytest.fixture(autouse=True)
def _isolate_verify_cache():
    """Ensure each test sees an empty module-level verify cache."""
    clear_verify_cache()
    yield
    clear_verify_cache()


def _secret_hash_cache(**overrides) -> TtlLruCache:
    """A cache configured the way VmDatabase configures its own."""
    kwargs = {
        "ttl": SECRET_HASH_POSITIVE_TTL_S,
        "negative_ttl": SECRET_HASH_NEGATIVE_TTL_S,
        "max_size": SECRET_HASH_CACHE_MAX_SIZE,
    }
    kwargs.update(overrides)
    return TtlLruCache(**kwargs)


# ── Existing argon2 wrapper tests ──────────────────────────────────────


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


# ── verify_secret_cached: correctness ──────────────────────────────────


def test_cached_verify_returns_true_for_correct_token():
    h = hash_secret("tk_correct")
    assert verify_secret_cached("host-1", "tk_correct", h) is True


def test_cached_verify_returns_false_for_wrong_token():
    h = hash_secret("tk_correct")
    assert verify_secret_cached("host-1", "tk_wrong", h) is False


def test_cached_verify_handles_garbage_hash():
    assert verify_secret_cached("host-1", "anything", "not-a-real-hash") is False


# ── verify_secret_cached: actually caches ──────────────────────────────


def test_second_correct_verify_skips_argon2():
    """The whole point of the cache: the second call for the same
    (subject, token) must not invoke argon2 again."""
    h = hash_secret("tk_a")
    assert verify_secret_cached("host-1", "tk_a", h) is True

    # Now any further call should hit the cache, not argon2.
    with patch.object(
        secret_hash, "verify_secret", wraps=secret_hash.verify_secret
    ) as spy:
        assert verify_secret_cached("host-1", "tk_a", h) is True
        spy.assert_not_called()


def test_failed_verify_is_not_cached():
    """A wrong token must always re-run argon2 — no fast path for
    attackers, and no false positives if the right token shows up later."""
    h = hash_secret("tk_correct")
    assert verify_secret_cached("host-1", "tk_wrong", h) is False

    with patch.object(
        secret_hash, "verify_secret", wraps=secret_hash.verify_secret
    ) as spy:
        assert verify_secret_cached("host-1", "tk_wrong", h) is False
        spy.assert_called_once()


def test_different_token_for_same_subject_bypasses_cache():
    """Caching the right token doesn't accept other tokens for that
    subject — the fingerprint key keeps them separate."""
    h = hash_secret("tk_a")
    assert verify_secret_cached("host-1", "tk_a", h) is True
    # Wrong token under the same hostname: not in cache (different fp),
    # so verify_secret runs and correctly rejects.
    assert verify_secret_cached("host-1", "tk_b", h) is False


def test_same_token_different_subject_is_isolated():
    """A token cached for host-A must not validate for host-B against a
    different stored hash."""
    h_a = hash_secret("shared_token")
    h_b = hash_secret("shared_token")  # different salt, different hash
    assert verify_secret_cached("host-A", "shared_token", h_a) is True

    # Cache for host-A doesn't carry over to host-B; argon2 must run.
    with patch.object(
        secret_hash, "verify_secret", wraps=secret_hash.verify_secret
    ) as spy:
        assert verify_secret_cached("host-B", "shared_token", h_b) is True
        spy.assert_called_once()


# ── invalidate_verify ──────────────────────────────────────────────────


def test_invalidate_verify_drops_entry():
    h = hash_secret("tk_a")
    verify_secret_cached("host-1", "tk_a", h)
    invalidate_verify("host-1")

    # Next call must re-run argon2.
    with patch.object(
        secret_hash, "verify_secret", wraps=secret_hash.verify_secret
    ) as spy:
        assert verify_secret_cached("host-1", "tk_a", h) is True
        spy.assert_called_once()


def test_invalidate_verify_only_targets_named_subject():
    h_a = hash_secret("tk_a")
    h_b = hash_secret("tk_b")
    verify_secret_cached("host-1", "tk_a", h_a)
    verify_secret_cached("host-2", "tk_b", h_b)

    invalidate_verify("host-1")

    # host-2's entry survives — argon2 must NOT run on the next call.
    with patch.object(
        secret_hash, "verify_secret", wraps=secret_hash.verify_secret
    ) as spy:
        assert verify_secret_cached("host-2", "tk_b", h_b) is True
        spy.assert_not_called()


def test_invalidate_unknown_subject_is_noop():
    """invalidate_verify on a subject that was never cached must not
    raise — it's called from register/unregister paths where the
    rotation may or may not have a stale cached entry."""
    invalidate_verify("never-registered")  # should not raise


# ── Cache mechanics: TTL, capacity ─────────────────────────────────────
# One class backs both caches, so these exercise it in the verify cache's
# shape: a compound (subject, token-fingerprint) key and no version guard.


def test_ttl_expiry():
    """After the TTL elapses, the cached entry is dropped and the caller
    is told to re-derive the value."""
    cache = TtlLruCache(ttl=0.01, max_size=8)
    key = ("host-1", _token_fingerprint("tk_a"))

    cache.put(key, True)
    assert cache.get(key)[0] is True

    import time as _time

    _time.sleep(0.02)
    assert cache.get(key)[0] is False


def test_lru_eviction_when_over_cap():
    """Beyond max_size, the least-recently-used entry is evicted."""
    cache = TtlLruCache(ttl=60.0, max_size=3)
    keys = [(f"host-{i}", _token_fingerprint(f"tk_{i}")) for i in range(4)]
    for key in keys[:3]:
        cache.put(key, True)
    # Inserting a 4th entry evicts host-0 (the LRU).
    cache.put(keys[3], True)

    assert cache.get(keys[0])[0] is False
    assert cache.get(keys[1])[0] is True
    assert cache.get(keys[2])[0] is True
    assert cache.get(keys[3])[0] is True


def test_lru_touch_on_get_preserves_recently_used():
    cache = TtlLruCache(ttl=60.0, max_size=3)
    keys = [(f"host-{i}", _token_fingerprint(f"tk_{i}")) for i in range(4)]
    for key in keys[:3]:
        cache.put(key, True)

    # Touch host-0 so it's no longer the LRU; host-1 should be evicted
    # when we insert a 4th entry.
    assert cache.get(keys[0])[0] is True
    cache.put(keys[3], True)

    assert cache.get(keys[0])[0] is True
    assert cache.get(keys[1])[0] is False
    assert cache.get(keys[2])[0] is True
    assert cache.get(keys[3])[0] is True


def test_negative_ttl_defaults_to_ttl_when_unset():
    """The verify cache passes no negative_ttl; a stored None must then
    expire on the positive TTL rather than immediately or never."""
    cache = TtlLruCache(ttl=60.0, max_size=8)
    cache.put("k", None)
    assert cache.get("k") == (True, None, 0)


def test_put_without_expected_version_skips_the_guard():
    """The verify cache never passes a version; an intervening
    invalidate must not be able to reject its writes."""
    cache = TtlLruCache(ttl=60.0, max_size=8)
    cache.invalidate("k")  # bumps version to 1
    assert cache.put("k", True) is True
    assert cache.get("k")[0] is True


# ── REGISTER_TOKEN_SUBJECT sentinel ────────────────────────────────────


def test_register_token_subject_is_a_distinct_namespace():
    """Register-token verifies must not collide with a hostname that
    happens to be the sentinel string."""
    h = hash_secret("register_token_value")
    verify_secret_cached(REGISTER_TOKEN_SUBJECT, "register_token_value", h)

    # A different subject sees a cold cache for the same token; argon2
    # runs.
    with patch.object(
        secret_hash, "verify_secret", wraps=secret_hash.verify_secret
    ) as spy:
        assert (
            verify_secret_cached("some-vm", "register_token_value", h) is True
        )
        spy.assert_called_once()


# ── Token fingerprint hygiene ──────────────────────────────────────────


def test_token_fingerprint_is_deterministic():
    assert _token_fingerprint("tk") == _token_fingerprint("tk")


def test_token_fingerprint_differs_for_different_inputs():
    assert _token_fingerprint("tk_a") != _token_fingerprint("tk_b")


def test_token_fingerprint_does_not_include_plaintext():
    """Plaintext token must not appear in the fingerprint (defense in
    depth against memory inspection of the cache's keys)."""
    fp = _token_fingerprint("totally_secret_token_value")
    assert "totally_secret_token_value" not in fp


# ── Secret-hash cache: TTLs, invalidate-race ───────────────────────────
# Same class as above, in the shape VmDatabase configures it: a plain
# hostname key, a shorter negative TTL, and the version guard in use.


def test_secret_hash_cache_ttl_expiry_re_queries():
    """Direct test of the cache primitive: after expiry, the next get is
    a miss and the caller must re-query."""
    cache = _secret_hash_cache(ttl=0.05, negative_ttl=0.05)
    assert cache.put("vm-1", "$h", expected_version=0) is True
    hit, val, _ = cache.get("vm-1")
    assert hit is True and val == "$h"

    import time as _time
    _time.sleep(0.08)

    hit, val, _ = cache.get("vm-1")
    assert hit is False and val is None


def test_secret_hash_cache_negative_entry_returns_hit_with_none():
    """A cached None must read back as (hit=True, value=None) so the
    caller short-circuits the DB query."""
    cache = _secret_hash_cache()
    assert cache.put("nope", None, expected_version=0) is True
    hit, val, _ = cache.get("nope")
    assert hit is True and val is None


def test_secret_hash_cache_negative_entry_expires_on_the_shorter_ttl():
    """A missing hostname is re-checked sooner than a real hash, so a
    freshly registered host becomes auth-able without an invalidate."""
    cache = _secret_hash_cache(ttl=60.0, negative_ttl=0.05)
    cache.put("not-yet-registered", None, expected_version=0)

    import time as _time
    _time.sleep(0.08)

    assert cache.get("not-yet-registered")[0] is False


def test_secret_hash_cache_invalidate_clears_entry():
    cache = _secret_hash_cache()
    cache.put("vm-1", "$h", expected_version=0)
    cache.invalidate("vm-1")
    hit, val, _ = cache.get("vm-1")
    assert hit is False and val is None


def test_secret_hash_cache_put_rejected_when_invalidate_races():
    """Simulate the rotate-race: reader gets a version, mid-flight
    invalidate (concurrent re-register) bumps it, reader's put must
    not commit the stale value."""
    cache = _secret_hash_cache()
    # Reader observes the version before the DB SELECT.
    hit, _, version = cache.get("vm-1")
    assert hit is False

    # Concurrent register_client rotates the secret and invalidates.
    cache.invalidate("vm-1")

    # Reader's SELECT returned the now-stale hash; put must be rejected.
    accepted = cache.put("vm-1", "$stale", expected_version=version)
    assert accepted is False

    # Cache stays empty so the next caller re-fetches and gets the
    # rotated value from the DB.
    hit, val, _ = cache.get("vm-1")
    assert hit is False and val is None


def test_secret_hash_cache_put_accepted_when_no_race():
    """Sanity check: with no intervening invalidate, put commits."""
    cache = _secret_hash_cache()
    hit, _, version = cache.get("vm-1")
    assert hit is False
    assert cache.put("vm-1", "$h", expected_version=version) is True
    hit, val, _ = cache.get("vm-1")
    assert hit is True and val == "$h"


def test_secret_hash_cache_version_bumped_per_hostname_only():
    """Invalidating vm-1 must not affect vm-2's version: a concurrent
    put for vm-2 must still succeed."""
    cache = _secret_hash_cache()
    _, _, v1 = cache.get("vm-1")
    _, _, v2 = cache.get("vm-2")
    cache.invalidate("vm-1")
    assert cache.put("vm-2", "$h2", expected_version=v2) is True
    assert cache.put("vm-1", "$h1", expected_version=v1) is False


def test_secret_hash_cache_lru_eviction_at_max_size():
    """When the cache is full, inserting a new entry evicts the LRU
    one. Bounds memory under unique-key floods."""
    cache = _secret_hash_cache(max_size=2)
    assert cache.put("a", "$a", expected_version=0) is True
    assert cache.put("b", "$b", expected_version=0) is True
    # Touch "a" so "b" becomes LRU.
    hit, _, _ = cache.get("a")
    assert hit is True
    # Inserting "c" should evict "b", not "a".
    assert cache.put("c", "$c", expected_version=0) is True
    assert cache.get("a")[0] is True
    assert cache.get("b")[0] is False
    assert cache.get("c")[0] is True


def test_secret_hash_cache_rejects_invalid_max_size():
    with pytest.raises(ValueError, match="Invalid cache max_size"):
        _secret_hash_cache(max_size=0)


def test_secret_hash_cache_clear_resets_versions():
    """clear() wipes entries and versions so a subsequent put against
    the old version is still accepted (no zombie versions)."""
    cache = _secret_hash_cache()
    cache.put("vm-1", "$h", expected_version=0)
    cache.invalidate("vm-1")  # bumps version to 1
    cache.clear()
    # After clear, version is back to 0 for any hostname.
    _, _, version = cache.get("vm-1")
    assert version == 0
    assert cache.put("vm-1", "$h2", expected_version=0) is True
