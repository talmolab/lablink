"""Tests for argon2 secret hashing helper and verify-result cache."""
from unittest.mock import patch

import pytest

from lablink_allocator_service import secret_hash
from lablink_allocator_service.secret_hash import (
    REGISTER_TOKEN_SUBJECT,
    _VerifyResultCache,
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


def test_ttl_expiry():
    """After the TTL elapses, the cached entry is dropped and argon2
    runs again on the next call."""
    cache = _VerifyResultCache(positive_ttl_seconds=0.01)
    fp = _token_fingerprint("tk_a")

    cache.mark_verified("host-1", fp)
    assert cache.is_verified("host-1", fp) is True

    import time as _time

    _time.sleep(0.02)
    assert cache.is_verified("host-1", fp) is False


def test_lru_eviction_when_over_cap():
    """Beyond max_size, the least-recently-used entry is evicted."""
    cache = _VerifyResultCache(max_size=3)
    fps = [_token_fingerprint(f"tk_{i}") for i in range(4)]
    for i, fp in enumerate(fps[:3]):
        cache.mark_verified(f"host-{i}", fp)
    # Inserting a 4th entry evicts host-0 (the LRU).
    cache.mark_verified("host-3", fps[3])

    assert cache.is_verified("host-0", fps[0]) is False
    assert cache.is_verified("host-1", fps[1]) is True
    assert cache.is_verified("host-2", fps[2]) is True
    assert cache.is_verified("host-3", fps[3]) is True


def test_lru_touch_on_get_preserves_recently_used():
    cache = _VerifyResultCache(max_size=3)
    fps = [_token_fingerprint(f"tk_{i}") for i in range(4)]
    for i, fp in enumerate(fps[:3]):
        cache.mark_verified(f"host-{i}", fp)

    # Touch host-0 so it's no longer the LRU; host-1 should be evicted
    # when we insert a 4th entry.
    assert cache.is_verified("host-0", fps[0]) is True
    cache.mark_verified("host-3", fps[3])

    assert cache.is_verified("host-0", fps[0]) is True
    assert cache.is_verified("host-1", fps[1]) is False
    assert cache.is_verified("host-2", fps[2]) is True
    assert cache.is_verified("host-3", fps[3]) is True


def test_invalid_max_size_rejected():
    with pytest.raises(ValueError):
        _VerifyResultCache(max_size=0)


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
