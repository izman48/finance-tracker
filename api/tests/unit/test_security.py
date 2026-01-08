"""Unit tests for security utilities."""
import pytest
from datetime import timedelta

from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    decode_access_token,
)


class TestPasswordHashing:
    """Tests for password hashing functions."""

    def test_hash_password(self):
        """Password should be hashed, not stored plain."""
        password = "mysecretpassword"
        hashed = get_password_hash(password)

        assert hashed != password
        assert len(hashed) > 20  # bcrypt hashes are long

    def test_verify_correct_password(self):
        """Correct password should verify."""
        password = "mysecretpassword"
        hashed = get_password_hash(password)

        assert verify_password(password, hashed) is True

    def test_verify_incorrect_password(self):
        """Incorrect password should not verify."""
        password = "mysecretpassword"
        hashed = get_password_hash(password)

        assert verify_password("wrongpassword", hashed) is False

    def test_different_hashes_for_same_password(self):
        """Same password should produce different hashes (salted)."""
        password = "mysecretpassword"
        hash1 = get_password_hash(password)
        hash2 = get_password_hash(password)

        assert hash1 != hash2
        # Both should still verify
        assert verify_password(password, hash1)
        assert verify_password(password, hash2)


class TestJWTTokens:
    """Tests for JWT token creation and validation."""

    def test_create_token(self):
        """Token should be created successfully."""
        token = create_access_token(data={"sub": "user-123"})

        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 50  # JWT tokens are reasonably long

    def test_decode_valid_token(self):
        """Valid token should decode to original data."""
        import uuid
        user_id = str(uuid.uuid4())
        token = create_access_token(data={"sub": user_id})

        token_data = decode_access_token(token)

        assert str(token_data.user_id) == user_id

    def test_decode_invalid_token(self):
        """Invalid token should raise HTTPException."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            decode_access_token("invalid.token.here")

        assert exc_info.value.status_code == 401

    def test_token_with_custom_expiry(self):
        """Token with custom expiry should work."""
        import uuid
        user_id = str(uuid.uuid4())
        token = create_access_token(
            data={"sub": user_id},
            expires_delta=timedelta(hours=1),
        )

        token_data = decode_access_token(token)
        assert str(token_data.user_id) == user_id
