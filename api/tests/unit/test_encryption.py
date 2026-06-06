"""Unit tests for the EncryptedString column type."""
import pytest

from app.core.encryption import EncryptedString, _get_fernet


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
