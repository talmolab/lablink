"""HMAC-SHA256 signed cookie value helpers.

Cookie format: <urlsafe-b64(payload)>.<urlsafe-b64(hmac)>
"""
import base64
import binascii
import hashlib
import hmac
import secrets as _secrets


class InvalidSignature(Exception):
    pass


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def sign(payload: str, *, secret: str) -> str:
    payload_bytes = payload.encode("utf-8")
    mac = hmac.new(
        secret.encode("utf-8"), payload_bytes, hashlib.sha256
    ).digest()
    return f"{_b64encode(payload_bytes)}.{_b64encode(mac)}"


def verify(token: str, *, secret: str) -> str:
    try:
        payload_b64, mac_b64 = token.split(".", 1)
        payload_bytes = _b64decode(payload_b64)
        provided_mac = _b64decode(mac_b64)
    except (ValueError, binascii.Error) as exc:
        raise InvalidSignature("malformed token") from exc
    expected_mac = hmac.new(
        secret.encode("utf-8"), payload_bytes, hashlib.sha256
    ).digest()
    if not hmac.compare_digest(provided_mac, expected_mac):
        raise InvalidSignature("hmac mismatch")
    return payload_bytes.decode("utf-8")


def get_or_create_cookie_secret(conn) -> str:
    """Read cookie_signing_secret from settings; create + persist on first use.

    `conn` is a psycopg2 connection. Caller owns the connection lifecycle.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT value FROM settings WHERE key = 'cookie_signing_secret'"
        )
        row = cur.fetchone()
        if row is not None:
            return row[0]
        new_secret = _secrets.token_urlsafe(32)
        cur.execute(
            "INSERT INTO settings (key, value) "
            "VALUES ('cookie_signing_secret', %s) "
            "ON CONFLICT (key) DO NOTHING",
            (new_secret,),
        )
        conn.commit()
        cur.execute(
            "SELECT value FROM settings WHERE key = 'cookie_signing_secret'"
        )
        return cur.fetchone()[0]
