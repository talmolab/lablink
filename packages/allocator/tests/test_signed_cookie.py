import pytest

from lablink_allocator_service.signed_cookie import (
    InvalidSignature,
    get_or_create_cookie_secret,
    sign,
    verify,
)

SECRET = "test-secret-32-bytes-do-not-use-prod"


def test_sign_verify_roundtrip():
    payload = "11111111-1111-1111-1111-111111111111"
    token = sign(payload, secret=SECRET)
    assert verify(token, secret=SECRET) == payload


def test_verify_rejects_tampered_token():
    payload = "11111111-1111-1111-1111-111111111111"
    token = sign(payload, secret=SECRET)
    tampered = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    with pytest.raises(InvalidSignature):
        verify(tampered, secret=SECRET)


def test_verify_rejects_different_secret():
    token = sign("payload", secret=SECRET)
    with pytest.raises(InvalidSignature):
        verify(token, secret="different-secret")


def test_verify_rejects_malformed_token_no_separator():
    # Triggers the ValueError branch (split returns one element)
    with pytest.raises(InvalidSignature):
        verify("not-a-real-token", secret=SECRET)


def test_verify_rejects_malformed_token_bad_base64():
    # Triggers the binascii.Error branch — non-base64 chars in the mac half
    with pytest.raises(InvalidSignature):
        verify("YWJj.@@@@@@@@", secret=SECRET)


def test_get_or_create_cookie_secret_creates_then_reuses(real_db):
    """The first call mints a secret and persists it; the second call reads it back."""
    conn = real_db._pool.getconn()
    try:
        # The real_db fixture creates a minimal vms table only. Create the
        # settings table inline for this test (production deployments get
        # it from generate_init_sql.py).
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS settings ("
                "  key TEXT PRIMARY KEY, "
                "  value TEXT NOT NULL"
                ")"
            )
            cur.execute("DELETE FROM settings WHERE key = 'cookie_signing_secret'")
        conn.commit()

        s1 = get_or_create_cookie_secret(conn)
        s2 = get_or_create_cookie_secret(conn)
        assert s1 == s2
        assert len(s1) >= 32
    finally:
        real_db._pool.putconn(conn)
