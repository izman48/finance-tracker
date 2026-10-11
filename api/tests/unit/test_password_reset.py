"""Unit tests for password reset tokens and categorization match keys, and
the purge that a reset without the recovery code performs."""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from jose import jwt

from app.core.security import (
    create_access_token,
    create_password_reset_token,
    get_password_hash,
    verify_password_reset_token,
)
from app.core import user_crypto
from app.core.config import get_settings
from app.models import AssetFlow, AssetValuation, User, merchant_match_key

PASSWORD = "securepassword123"
NEW_PASSWORD = "afterreset12345"
EMAIL = "purge@example.com"


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


def _login(client, password=PASSWORD) -> str:
    res = client.post("/api/v1/auth/login", data={"username": EMAIL, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _dek_from_token(access_token: str) -> bytes:
    payload = jwt.decode(access_token, get_settings().secret_key, algorithms=["HS256"])
    return user_crypto.unwrap_session_dek(payload["dk"])


def _seed_user_content(client, db_session, token):
    """A commitment, a planned item, an asset with a valuation and a flow, and a
    rule in a pack: all of it encrypted under the user's current key."""
    headers = {"Authorization": f"Bearer {token}"}
    assert client.post(
        "/api/v1/analytics/commitments",
        json={"direction": "expense", "label": "Rent", "amount": "950", "next_date": "2026-11-01"},
        headers=headers,
    ).status_code == 201
    assert client.post(
        "/api/v1/analytics/planned-items",
        json={"name": "Holiday", "kind": "one_off", "start_date": "2026-12-01", "amount": "600"},
        headers=headers,
    ).status_code == 201
    asset = client.post("/api/v1/assets", json={"name": "ISA", "asset_type": "isa", "value": "1000"}, headers=headers)
    assert asset.status_code == 201
    asset_id = asset.json()["id"]
    # Written directly: the asset sub-routes look the asset up by its string id,
    # which SQLite's UUID type can't bind.
    dek = user_crypto.current_dek.set(_dek_from_token(token))
    try:
        db_session.add(AssetValuation(asset_id=uuid.UUID(asset_id), value=Decimal("1100"), valued_at=date(2026, 10, 1)))
        db_session.add(AssetFlow(asset_id=uuid.UUID(asset_id), amount=Decimal("50"), flow_date=date(2026, 10, 1)))
        db_session.commit()
    finally:
        user_crypto.current_dek.reset(dek)
    assert client.post(
        "/api/v1/rules/packs/bulk",
        json={"name": "Mine", "rules": [{"pattern": "TESCO", "category": "Groceries"}], "apply": False},
        headers=headers,
    ).status_code == 201


def _reset_without_recovery_code(client, db_session):
    user = db_session.query(User).filter(User.email == EMAIL).one()
    res = client.post(
        "/api/v1/auth/reset-password",
        json={"token": create_password_reset_token(user), "new_password": NEW_PASSWORD},
    )
    assert res.status_code == 200, res.text
    return res.json()


class TestResetWithoutRecoveryCode:
    def test_user_content_is_cleared_and_every_list_loads_empty(self, client, db_session):
        client.post("/api/v1/auth/register", json={"email": EMAIL, "password": PASSWORD})
        _seed_user_content(client, db_session, _login(client))

        _reset_without_recovery_code(client, db_session)

        fresh = {"Authorization": f"Bearer {_login(client, NEW_PASSWORD)}"}
        for path in ("/api/v1/analytics/commitments", "/api/v1/analytics/planned-items", "/api/v1/assets"):
            res = client.get(path, headers=fresh)
            assert res.status_code == 200, (path, res.text)
            assert res.json() == [], path
        rules = client.get("/api/v1/rules", headers=fresh)
        assert rules.status_code == 200, rules.text
        assert rules.json() == {"packs": [], "personal": []}
