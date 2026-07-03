"""Unit tests for the encrypted column types."""
from decimal import Decimal

import pytest

from app.core import user_crypto
from app.core.encryption import (
    EncryptedString,
    UserEncryptedDecimal,
    UserEncryptedString,
    UserEncryptedToken,
    _get_fernet,
)
from app.core.user_crypto import DEKUnavailableError


class TestEncryptedString:
    """Round-trip and at-rest behaviour for encrypted columns."""

    def setup_method(self):
        self.col = EncryptedString()

    def test_roundtrip(self):
        """A value encrypted on bind decrypts back on load."""
        stored = self.col.process_bind_param("super-secret-token", dialect=None)
        loaded = self.col.process_result_value(stored, dialect=None)
        assert loaded == "super-secret-token"

    def test_value_is_encrypted_at_rest(self):
        """The stored value is ciphertext, not the plaintext."""
        plaintext = "super-secret-token"
        stored = self.col.process_bind_param(plaintext, dialect=None)
        assert stored is not None
        assert plaintext not in stored
        # Fernet tokens are urlsafe-base64 starting with the version byte 'gA'.
        assert stored.startswith("gA")

    def test_none_passthrough(self):
        """None is stored/loaded as None (nullable columns)."""
        assert self.col.process_bind_param(None, dialect=None) is None
        assert self.col.process_result_value(None, dialect=None) is None

    def test_legacy_plaintext_is_returned_as_is(self):
        """A pre-encryption plaintext value is returned unchanged, not an error."""
        assert self.col.process_result_value("legacy-plain-token", dialect=None) == (
            "legacy-plain-token"
        )

    def test_distinct_ciphertexts(self):
        """Fernet includes a random IV, so encryptions differ but both decrypt."""
        a = self.col.process_bind_param("same", dialect=None)
        b = self.col.process_bind_param("same", dialect=None)
        assert a != b
        assert _get_fernet().decrypt(a.encode()).decode() == "same"


@pytest.fixture
def no_dek():
    """Clear the session DEK (the conftest autouse fixture sets one)."""
    token = user_crypto.current_dek.set(None)
    yield
    user_crypto.current_dek.reset(token)


class TestUserEncryptedTypes:
    """Column types keyed by the per-user DEK from the request context."""

    def test_string_roundtrip_and_at_rest(self):
        col = UserEncryptedString()
        stored = col.process_bind_param("Coffee Shop", dialect=None)
        assert "Coffee" not in stored
        assert col.process_result_value(stored, dialect=None) == "Coffee Shop"

    def test_decimal_roundtrip(self):
        col = UserEncryptedDecimal()
        stored = col.process_bind_param(9.99, dialect=None)
        assert "9.99" not in stored
        assert col.process_result_value(stored, dialect=None) == Decimal("9.99")

    def test_none_passthrough(self):
        for col in (UserEncryptedString(), UserEncryptedDecimal(), UserEncryptedToken()):
            assert col.process_bind_param(None, dialect=None) is None
            assert col.process_result_value(None, dialect=None) is None

    def test_fails_closed_without_dek(self, no_dek):
        with pytest.raises(DEKUnavailableError):
            UserEncryptedString().process_bind_param("x", dialect=None)
        with pytest.raises(DEKUnavailableError):
            UserEncryptedString().process_result_value("gAAAA", dialect=None)

    def test_wrong_dek_cannot_decrypt(self):
        stored = UserEncryptedString().process_bind_param("secret", dialect=None)
        other = user_crypto.current_dek.set(user_crypto.generate_dek())
        try:
            with pytest.raises(Exception):  # InvalidToken — never plaintext fallback
                UserEncryptedString().process_result_value(stored, dialect=None)
        finally:
            user_crypto.current_dek.reset(other)

    def test_token_type_is_double_wrapped(self):
        """Bank tokens: server key outside, user key inside."""
        col = UserEncryptedToken()
        stored = col.process_bind_param("tl-token", dialect=None)
        # Outer layer opens with the server key alone…
        inner = _get_fernet().decrypt(stored.encode())
        # …but the inner layer is still ciphertext without the DEK.
        assert b"tl-token" not in inner
        assert col.process_result_value(stored, dialect=None) == "tl-token"
