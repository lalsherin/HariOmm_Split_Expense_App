"""Tokens and hashing.

Sessions use opaque random tokens rather than JWTs. Section 9 of the spec
allows "an equivalent secure session architecture", and opaque tokens are the
better trade here: a sign-out or a stolen phone can be revoked instantly by
one UPDATE, where a self-contained JWT stays valid until it expires unless a
denylist is bolted on — which reintroduces the database lookup that JWTs were
supposed to avoid.

Tokens are stored only as SHA-256 hashes, so a leak of the sessions table
cannot be replayed against the API. They are 256 bits of urandom, so there is
nothing to brute-force and no need for a slow KDF.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_otp(code: str, mobile: str) -> str:
    """OTPs are short enough to brute-force a bare hash, so they are bound to
    the number and stretched. Never stored in the clear."""
    return hashlib.pbkdf2_hmac(
        "sha256", code.encode("utf-8"), ("otp:" + mobile).encode("utf-8"), 50_000
    ).hex()


def check_otp(code: str, mobile: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_otp(code, mobile), expected_hash)


def new_otp(length: int = 4) -> str:
    """Cryptographically secure, and zero-padded so every code is `length`
    digits — `secrets.randbelow` alone would produce '42' for 4 digits."""
    upper = 10 ** length
    return str(secrets.randbelow(upper)).zfill(length)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def in_minutes(n: int) -> datetime:
    return utcnow() + timedelta(minutes=n)


def in_days(n: int) -> datetime:
    return utcnow() + timedelta(days=n)


def as_aware(dt: datetime) -> datetime:
    """SQLite hands back naive datetimes; treat those as UTC so comparisons
    against timezone-aware `now` do not explode."""
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
