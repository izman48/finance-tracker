"""POST /rules/packs/bulk — create a whole pack in one reviewed request.

The safety properties under test are what make this acceptable as a write path:
it validates everything before writing anything, it only ever adds a new pack,
and deleting that pack removes the lot.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from jose import jwt

from app.core import user_crypto
from app.core.config import get_settings
from app.models import Account, BankConnection, CategoryRule, RulePack, Transaction, User

SECRET = get_settings().secret_key


def _setup(client, db_session, email="bulk@example.com"):
    client.post("/api/v1/auth/register", json={"email": email, "password": "securepassword123"})
    token = client.post(
        "/api/v1/auth/login", data={"username": email, "password": "securepassword123"}
    ).json()["access_token"]
    dek = user_crypto.unwrap_session_dek(jwt.decode(token, SECRET, algorithms=["HS256"])["dk"])
    client.headers["Authorization"] = f"Bearer {token}"
    user = db_session.query(User).filter(User.email == email).first()
    return user, user_crypto.current_dek.set(dek)


def _txns(db, user_id, rows):
    conn = BankConnection(
        user_id=user_id, provider_id="ob-bulk", provider_name="Test Bank",
        access_token="t", refresh_token="r",
    )
    db.add(conn)
    db.flush()
    acc = Account(
        user_id=user_id, bank_connection_id=conn.id, external_id=f"ext-{uuid.uuid4()}",
        provider_name="Test Bank", account_type="TRANSACTION", display_name="Cur",
        current_balance=Decimal("0"),
    )
    db.add(acc)
    db.commit()
    for desc, amount in rows:
        db.add(Transaction(
            account_id=acc.id, external_id=f"tx-{uuid.uuid4()}", transaction_type="debit",
            amount=Decimal(str(amount)), currency="GBP", description=desc, merchant_name=desc,
            transaction_date=datetime(2026, 7, 10, tzinfo=timezone.utc),
        ))
    db.commit()


PACK = {
    "name": "Starter",
    "description": "built from my own history",
    "rules": [
        {"pattern": "TESCO", "category": "Groceries"},
        {"pattern": "NEW BANK APP", "category": "Transfers", "counts_as": "transfer"},
        {"pattern": "Loan", "match_type": "exact", "category": "Debt"},
    ],
}


def test_creates_pack_with_rules_and_backfills(client, db_session):
    user, ctx = _setup(client, db_session)
    try:
        _txns(db_session, user.id, [("TESCO METRO", 20), ("NEW BANK APP", 500), ("Loan", 217)])
    finally:
        user_crypto.current_dek.reset(ctx)

    res = client.post("/api/v1/rules/packs/bulk", json=PACK)
    assert res.status_code == 201
    body = res.json()
    assert body["rules_created"] == 3
    assert body["transactions_recategorized"] == 3  # backfill ran

    listed = client.get("/api/v1/rules").json()
    pack = next(p for p in listed["packs"] if p["name"] == "Starter")
    assert len(pack["rules"]) == 3


def test_a_bad_pattern_writes_nothing(client, db_session):
    """Validation runs over every rule before the first insert, so a broken
    regex can't leave half a pack behind."""
    user, ctx = _setup(client, db_session, email="badpat@example.com")
    user_crypto.current_dek.reset(ctx)

    res = client.post("/api/v1/rules/packs/bulk", json={
        "name": "Broken",
        "rules": [
            {"pattern": "TESCO", "category": "Groceries"},
            {"pattern": "([unclosed", "match_type": "regex", "category": "Oops"},
        ],
    })
    assert res.status_code == 400
    assert "rule 1" in res.json()["detail"]

    assert db_session.query(RulePack).filter(RulePack.user_id == user.id).count() == 0
    assert db_session.query(CategoryRule).filter(CategoryRule.user_id == user.id).count() == 0


def test_apply_false_creates_without_backfilling(client, db_session):
    user, ctx = _setup(client, db_session, email="noapply@example.com")
    try:
        _txns(db_session, user.id, [("TESCO METRO", 20)])
    finally:
        user_crypto.current_dek.reset(ctx)

    res = client.post("/api/v1/rules/packs/bulk", json={**PACK, "apply": False})
    assert res.status_code == 201
    assert res.json()["transactions_recategorized"] == 0


def test_deleting_the_pack_removes_its_rules(client, db_session):
    """The undo story: one delete takes the whole pack with it."""
    user, ctx = _setup(client, db_session, email="undo@example.com")
    user_crypto.current_dek.reset(ctx)

    pack_id = client.post("/api/v1/rules/packs/bulk", json=PACK).json()["pack_id"]
    assert client.delete(f"/api/v1/rules/packs/{pack_id}").status_code == 200
    assert db_session.query(CategoryRule).filter(CategoryRule.user_id == user.id).count() == 0


def test_requires_authentication(client):
    assert client.post("/api/v1/rules/packs/bulk", json=PACK).status_code == 401
