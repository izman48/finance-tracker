"""Unit tests for password reset tokens and categorization match keys."""
import uuid

import pytest

from app.core.security import (
    create_access_token,
    create_password_reset_token,
    get_password_hash,
    verify_password_reset_token,
)
from app.models import User, merchant_match_key


class FakeQuery:
    def __init__(self, user):
        self._user = user

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._user


class FakeDb:
    """Minimal stand-in for a Session: returns one canned user."""

    def __init__(self, user):
        self._user = user

    def query(self, model):
        return FakeQuery(self._user)


def make_user(password="originalpass123"):
    return User(
        id=uuid.uuid4(),
        email="reset-test@example.com",
        hashed_password=get_password_hash(password),
    )


class TestPasswordResetToken:
    def test_roundtrip_returns_user(self):
        user = make_user()
        token = create_password_reset_token(user)
        assert verify_password_reset_token(token, FakeDb(user)) is user

    def test_token_invalid_after_password_change(self):
        """Tokens are single-use: changing the password invalidates them."""
        user = make_user()
        token = create_password_reset_token(user)
        user.hashed_password = get_password_hash("brand-new-password")
        with pytest.raises(ValueError):
            verify_password_reset_token(token, FakeDb(user))

    def test_access_token_rejected(self):
        """A login JWT must not work as a reset token."""
        user = make_user()
        access = create_access_token({"sub": str(user.id)})
        with pytest.raises(ValueError):
            verify_password_reset_token(access, FakeDb(user))

    def test_garbage_rejected(self):
        user = make_user()
        with pytest.raises(ValueError):
            verify_password_reset_token("not-a-token", FakeDb(user))


class TestMerchantMatchKey:
    def test_prefers_merchant_name(self):
        assert merchant_match_key("Tesco Stores", "CARD PAYMENT 1234") == "tesco stores"

    def test_falls_back_to_description(self):
        assert merchant_match_key(None, "  SPOTIFY P31AB  ") == "spotify p31ab"
        assert merchant_match_key("", "SPOTIFY") == "spotify"

    def test_empty_everything_is_none(self):
        assert merchant_match_key(None, None) is None
        assert merchant_match_key(" ", "") is None
