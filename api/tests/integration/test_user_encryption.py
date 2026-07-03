"""End-to-end tests for per-user encryption: signup/login key handling,
recovery codes, password change/reset, and encrypted columns at rest."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from jose import jwt
from sqlalchemy import text

from app.core import user_crypto
from app.core.config import get_settings
from app.core.security import create_password_reset_token, get_password_hash
from app.models import Account, BankConnection, Transaction, User

SECRET = get_settings().secret_key


def _register(client, email="enc@example.com", password="securepassword123"):
    res = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert res.status_code == 201
    return res.json()


def _login(client, email="enc@example.com", password="securepassword123"):
    res = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert res.status_code == 200
    return res.json()


def _dek_from_token(access_token: str) -> bytes:
    payload = jwt.decode(access_token, SECRET, algorithms=["HS256"])
    assert payload.get("dk"), "access token must carry the wrapped DEK"
    return user_crypto.unwrap_session_dek(payload["dk"])


def _seed_bank_data(db, user_id: uuid.UUID, dek: bytes):
    """Insert a connection, account and transaction under the given DEK."""
    ctx = user_crypto.current_dek.set(dek)
    try:
        conn = BankConnection(
            user_id=user_id,
            provider_id="ob-testbank",
            provider_name="Test Bank",
            access_token="tl-access-token",
            refresh_token="tl-refresh-token",
        )
        db.add(conn)
        db.flush()
        account = Account(
            user_id=user_id,
            bank_connection_id=conn.id,
            external_id=f"acc-{uuid.uuid4()}",
            provider_name="Test Bank",
            account_type="TRANSACTION",
            display_name="Main Current Account",
            current_balance=Decimal("123.45"),
        )
        db.add(account)
        db.flush()
        tx = Transaction(
            account_id=account.id,
            external_id=f"tx-{uuid.uuid4()}",
            transaction_type="debit",
            amount=Decimal("9.99"),
            description="COFFEE SHOP LONDON",
            merchant_name="Coffee Shop",
            transaction_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        db.add(tx)
        db.commit()
        return conn.id
    finally:
        user_crypto.current_dek.reset(ctx)


class TestRegistration:
    def test_register_returns_one_time_recovery_code(self, client):
        data = _register(client)
        code = data["recovery_code"]
        groups = code.split("-")
        assert len(groups) == 8 and all(len(g) == 4 for g in groups)

    def test_register_stores_only_wrapped_keys(self, client, db_session):
        _register(client)
        user = db_session.query(User).first()
        assert user.wrapped_dek and user.recovery_wrapped_dek
        assert user.dek_salt and user.recovery_salt
        assert user.wrapped_dek != user.recovery_wrapped_dek


class TestLoginDEK:
    def test_login_token_carries_unwrappable_dek(self, client):
        _register(client)
        token = _login(client)["access_token"]
        dek = _dek_from_token(token)
        assert len(dek) == 44  # a Fernet key

    def test_recovery_code_wraps_the_same_dek(self, client, db_session):
        reg = _register(client)
        token = _login(client)["access_token"]
        dek = _dek_from_token(token)
        user = db_session.query(User).first()
        recovered = user_crypto.unwrap_dek(
            user.recovery_wrapped_dek,
            user_crypto.normalize_recovery_code(reg["recovery_code"]),
            user.recovery_salt,
        )
        assert recovered == dek

    def test_legacy_user_gets_dek_provisioned_at_login(self, client, db_session):
        user = User(
            email="legacy@example.com",
            hashed_password=get_password_hash("legacypassword1"),
        )
        db_session.add(user)
        db_session.commit()

        body = _login(client, "legacy@example.com", "legacypassword1")
        assert body["recovery_code"]  # shown once, at provisioning
        db_session.refresh(user)
        assert user.wrapped_dek
        # Second login: no new code, DEK still unwraps.
        body2 = _login(client, "legacy@example.com", "legacypassword1")
        assert body2["recovery_code"] is None
        assert _dek_from_token(body2["access_token"])


class TestEncryptedData:
    def test_data_readable_in_session_and_ciphertext_at_rest(self, client, db_session):
        _register(client)
        token = _login(client)["access_token"]
        dek = _dek_from_token(token)
        user = db_session.query(User).first()
        _seed_bank_data(db_session, user.id, dek)

        client.headers["Authorization"] = f"Bearer {token}"
        res = client.get("/api/v1/banking/transactions")
        assert res.status_code == 200
        item = res.json()["items"][0]
        assert item["description"] == "COFFEE SHOP LONDON"
        assert item["merchant_name"] == "Coffee Shop"
        assert float(item["amount"]) == 9.99

        # At rest: raw column values are Fernet ciphertext, not plaintext.
        raw = db_session.execute(
            text("SELECT description, merchant_name, amount FROM transactions")
        ).one()
        for stored in raw:
            assert "COFFEE" not in stored.upper()
            assert stored.startswith("gA")
        raw_tokens = db_session.execute(
            text("SELECT access_token, provider_name FROM bank_connections")
        ).one()
        assert "tl-access-token" not in raw_tokens[0]
        assert "Test Bank" not in raw_tokens[1]

    def test_reading_without_dek_is_401_not_leak(self, client, db_session):
        """A token without a `dk` claim (predates encryption) can't read data."""
        _register(client)
        token = _login(client)["access_token"]
        dek = _dek_from_token(token)
        user = db_session.query(User).first()
        _seed_bank_data(db_session, user.id, dek)

        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
        del payload["dk"]
        legacy_token = jwt.encode(payload, SECRET, algorithm="HS256")
        client.headers["Authorization"] = f"Bearer {legacy_token}"
        res = client.get("/api/v1/banking/transactions")
        assert res.status_code == 401


class TestPasswordChange:
    def test_change_password_rewraps_dek(self, client, db_session):
        _register(client)
        login1 = _login(client)
        dek_before = _dek_from_token(login1["access_token"])

        client.headers["Authorization"] = f"Bearer {login1['access_token']}"
        res = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "securepassword123", "new_password": "evenmoresecure456"},
        )
        assert res.status_code == 200

        login2 = _login(client, password="evenmoresecure456")
        assert _dek_from_token(login2["access_token"]) == dek_before  # same key, no data loss

    def test_change_password_wrong_current_rejected(self, client):
        _register(client)
        token = _login(client)["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        res = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "wrong-password", "new_password": "evenmoresecure456"},
        )
        assert res.status_code == 403


class TestPasswordReset:
    def test_reset_with_recovery_code_keeps_dek(self, client, db_session):
        reg = _register(client)
        dek_before = _dek_from_token(_login(client)["access_token"])
        user = db_session.query(User).first()

        reset_token = create_password_reset_token(user)
        res = client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": reset_token,
                "new_password": "afterreset12345",
                # Deliberately messy: normalization should accept it.
                "recovery_code": reg["recovery_code"].lower().replace("-", " "),
            },
        )
        assert res.status_code == 200

        dek_after = _dek_from_token(_login(client, password="afterreset12345")["access_token"])
        assert dek_after == dek_before

    def test_reset_with_wrong_recovery_code_rejected_and_token_reusable(self, client, db_session):
        _register(client)
        _login(client)
        user = db_session.query(User).first()
        reset_token = create_password_reset_token(user)

        res = client.post(
            "/api/v1/auth/reset-password",
            json={
                "token": reset_token,
                "new_password": "afterreset12345",
                "recovery_code": "AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA",
            },
        )
        assert res.status_code == 400
        # The typo didn't consume the token: retrying with the right code works
        # (proven by the token still validating for a code-less reset).
        res2 = client.post(
            "/api/v1/auth/reset-password",
            json={"token": reset_token, "new_password": "afterreset12345"},
        )
        assert res2.status_code == 200

    def test_reset_without_recovery_code_purges_and_reissues(self, client, db_session):
        _register(client)
        login = _login(client)
        dek_before = _dek_from_token(login["access_token"])
        user = db_session.query(User).first()
        _seed_bank_data(db_session, user.id, dek_before)

        reset_token = create_password_reset_token(user)
        res = client.post(
            "/api/v1/auth/reset-password",
            json={"token": reset_token, "new_password": "afterreset12345"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["recovery_code"]  # a fresh one-time code
        assert db_session.query(BankConnection).count() == 0  # unreadable data purged

        dek_after = _dek_from_token(_login(client, password="afterreset12345")["access_token"])
        assert dek_after != dek_before  # old key is gone, by design
