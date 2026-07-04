"""Unit tests for per-user envelope encryption (DEK/KEK/recovery codes)."""
import pytest
from cryptography.fernet import InvalidToken

from app.core import user_crypto
from app.core.user_crypto import (
    DEKUnavailableError,
    current_dek,
    generate_dek,
    generate_recovery_code,
    generate_salt,
    normalize_recovery_code,
    unwrap_dek,
    unwrap_session_dek,
    wrap_dek,
    wrap_dek_for_session,
)


class TestDEKWrapping:
    """Wrapping a DEK under a password-derived KEK."""

    def test_wrap_unwrap_roundtrip(self):
        dek = generate_dek()
        salt = generate_salt()
        wrapped = wrap_dek(dek, "correct horse battery", salt)
        assert unwrap_dek(wrapped, "correct horse battery", salt) == dek

    def test_wrapped_dek_is_not_the_dek(self):
        dek = generate_dek()
        salt = generate_salt()
        assert dek.decode() not in wrap_dek(dek, "pw", salt)

    def test_wrong_password_fails(self):
        dek = generate_dek()
        salt = generate_salt()
        wrapped = wrap_dek(dek, "right-password", salt)
        with pytest.raises(InvalidToken):
            unwrap_dek(wrapped, "wrong-password", salt)

    def test_wrong_salt_fails(self):
        dek = generate_dek()
        wrapped = wrap_dek(dek, "pw", generate_salt())
        with pytest.raises(InvalidToken):
            unwrap_dek(wrapped, "pw", generate_salt())

    def test_deks_are_unique(self):
        assert generate_dek() != generate_dek()


class TestRecoveryCodes:
    def test_format(self):
        """Groups of 4 uppercase base32 characters, dash-separated."""
        code = generate_recovery_code()
        groups = code.split("-")
        assert len(groups) == 8
        assert all(len(g) == 4 for g in groups)
        assert code == code.upper()

    def test_codes_are_unique(self):
        assert generate_recovery_code() != generate_recovery_code()

    def test_normalize_accepts_messy_input(self):
        code = generate_recovery_code()
        messy = f"  {code.lower().replace('-', ' ')}  "
        assert normalize_recovery_code(messy) == code.replace("-", "")

    def test_recovery_code_wraps_dek(self):
        """A recovery code works as a wrapping secret like a password."""
        dek = generate_dek()
        salt = generate_salt()
        code = generate_recovery_code()
        wrapped = wrap_dek(dek, normalize_recovery_code(code), salt)
        # Unwrap with a messy re-typing of the same code.
        retyped = normalize_recovery_code(code.lower().replace("-", " "))
        assert unwrap_dek(wrapped, retyped, salt) == dek


class TestSessionWrapping:
    """DEK-in-JWT transport: wrapped under the server key, never plaintext."""

    def test_session_roundtrip(self):
        dek = generate_dek()
        token = wrap_dek_for_session(dek)
        assert dek.decode() not in token
        assert unwrap_session_dek(token) == dek

    def test_garbage_session_token_fails(self):
        with pytest.raises(InvalidToken):
            unwrap_session_dek("not-a-real-token")


class TestDEKContext:
    def test_get_without_context_raises(self):
        token = current_dek.set(None)  # conftest autouse fixture sets one
        try:
            with pytest.raises(DEKUnavailableError):
                user_crypto.require_dek()
        finally:
            current_dek.reset(token)

    def test_set_and_get(self):
        dek = generate_dek()
        token = current_dek.set(dek)
        try:
            assert user_crypto.require_dek() == dek
        finally:
            current_dek.reset(token)
