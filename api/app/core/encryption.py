"""Transparent encryption for sensitive columns.

``EncryptedString`` encrypts with the server-wide Fernet key — it protects
against database leaks but the operator can decrypt.

``UserEncryptedString`` / ``UserEncryptedDecimal`` encrypt with the current
user's DEK (see ``core/user_crypto.py``), which the server only holds during
an authenticated session — the operator cannot decrypt these at rest.
``UserEncryptedToken`` adds the server key as an outer layer on top of the
DEK layer (used for bank OAuth tokens, which were already server-encrypted).

All types fail closed: touching a user-encrypted column without a session DEK
raises ``DEKUnavailableError`` (mapped to a 401 asking to re-login).
"""
from decimal import Decimal
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String, Text, TypeDecorator

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


def _user_fernet() -> Fernet:
    """Fernet cipher over the current session's DEK (fail-closed)."""
    from app.core.user_crypto import require_dek

    return Fernet(require_dek())


class UserEncryptedString(TypeDecorator):
    """A Text column encrypted with the user's DEK at rest."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return _user_fernet().encrypt(str(value).encode()).decode()

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return _user_fernet().decrypt(value.encode()).decode()


class UserEncryptedDecimal(TypeDecorator):
    """A Decimal stored as DEK-encrypted text.

    SQL cannot aggregate or compare it — all arithmetic on these columns
    happens in Python (which is how the analytics engine already works).
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect) -> str | None:
        if value is None:
            return None
        return _user_fernet().encrypt(str(Decimal(str(value))).encode()).decode()

    def process_result_value(self, value: str | None, dialect) -> Decimal | None:
        if value is None:
            return None
        return Decimal(_user_fernet().decrypt(value.encode()).decode())


class UserEncryptedToken(TypeDecorator):
    """DEK layer inside, server-key layer outside (bank OAuth tokens).

    Keeps the pre-existing server-side Fernet layer while adding the per-user
    one, so a leaked database needs both the server key *and* a user secret.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        inner = _user_fernet().encrypt(value.encode())
        return _get_fernet().encrypt(inner).decode()

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        inner = _get_fernet().decrypt(value.encode())
        return _user_fernet().decrypt(inner).decode()
