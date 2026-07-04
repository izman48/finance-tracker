"""Unit tests for security utilities."""
import pytest
from datetime import timedelta

from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    decode_access_token,
    create_oauth_state,
    verify_oauth_state,
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

    def test_oauth_state_token_not_accepted_as_access(self):
        """An oauth_state token must not authenticate as an access token."""
        from fastapi import HTTPException

        state = create_oauth_state("user-abc")
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(state)
        assert exc_info.value.status_code == 401

    def test_reset_token_not_accepted_as_access(self):
        """A password-reset token must not authenticate as an access token."""
        from fastapi import HTTPException
        from jose import jwt
        from datetime import datetime, timezone
        from app.core.config import get_settings

        # Mint a reset-shaped token directly (avoids needing a User row here).
        settings = get_settings()
        reset = jwt.encode(
            {
                "sub": "user-abc",
                "typ": "pwd_reset",
                "fp": "deadbeefdeadbeef",
                "nonce": "x",
                "exp": datetime.now(timezone.utc) + timedelta(minutes=30),
            },
            settings.secret_key,
            algorithm=settings.algorithm,
        )
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(reset)
        assert exc_info.value.status_code == 401

    def test_typeless_legacy_token_rejected(self):
        """A token with no `typ` claim (e.g. pre-fix) is rejected as access."""
        from fastapi import HTTPException
        from jose import jwt
        from datetime import datetime, timezone
        from app.core.config import get_settings

        settings = get_settings()
        legacy = jwt.encode(
            {"sub": "user-abc", "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
            settings.secret_key,
            algorithm=settings.algorithm,
        )
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(legacy)
        assert exc_info.value.status_code == 401


class TestOAuthState:
    """Tests for the signed OAuth state token (CSRF protection)."""

    def test_roundtrip_returns_user_id(self):
        """A freshly created state verifies back to the same user_id."""
        state = create_oauth_state("user-abc")
        assert verify_oauth_state(state) == ("user-abc", None)

    def test_roundtrip_carries_session_dek(self):
        """The state token transports the session DEK to the OAuth callback."""
        from app.core.user_crypto import generate_dek

        dek = generate_dek()
        state = create_oauth_state("user-abc", dek)
        assert dek.decode() not in state  # never in the clear in a URL
        assert verify_oauth_state(state) == ("user-abc", dek)

    def test_distinct_states_per_call(self):
        """Random nonce makes each state token unique."""
        assert create_oauth_state("user-abc") != create_oauth_state("user-abc")

    def test_tampered_state_rejected(self):
        """A garbage/forged state token is rejected."""
        with pytest.raises(ValueError):
            verify_oauth_state("not-a-real-token")

    def test_access_token_not_accepted_as_state(self):
        """A normal access token must not pass as an oauth_state token."""
        access = create_access_token(data={"sub": "user-abc"})
        with pytest.raises(ValueError):
            verify_oauth_state(access)

    def test_expired_state_rejected(self):
        """An expired state token is rejected."""
        from jose import jwt
        from datetime import datetime, timezone
        from app.core.config import get_settings

        settings = get_settings()
        expired = jwt.encode(
            {
                "sub": "user-abc",
                "typ": "oauth_state",
                "nonce": "x",
                "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
            },
            settings.secret_key,
            algorithm=settings.algorithm,
        )
        with pytest.raises(ValueError):
            verify_oauth_state(expired)
