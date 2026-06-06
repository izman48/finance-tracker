"""Transparent encryption for sensitive columns (bank OAuth tokens).

Provides an ``EncryptedString`` SQLAlchemy type that encrypts values with
Fernet (AES-128-CBC + HMAC) on the way into the database and decrypts them on
the way out, so callers and queries see plain strings while data at rest is
ciphertext.
"""
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, TypeDecorator

from app.core.config import get_settings


@lru_cache
def _get_fernet() -> Fernet:
    """Build the Fernet cipher from the configured ENCRYPTION_KEY."""
    settings = get_settings()
    if not settings.encryption_key:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` and add it to your .env."
        )
    try:
        return Fernet(settings.encryption_key.encode())
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            "ENCRYPTION_KEY is not a valid Fernet key (urlsafe base64, 32 bytes)."
        ) from exc


class EncryptedString(TypeDecorator):
    """A String column whose value is Fernet-encrypted at rest."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return _get_fernet().encrypt(value.encode()).decode()

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        try:
            return _get_fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # Value predates encryption (legacy plaintext) or was written with a
            # different key. Return as-is so reads don't hard-fail; such rows
            # should be re-created via a fresh bank connection.
            return value
