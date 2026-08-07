"""GET /rules/impact — what existing rules actually do, and what they miss.

The distinction under test is matched vs effective: rules apply best-first, so
a rule can match plenty and decide nothing. Reporting only `matched` would tell
the user a shadowed rule is pulling its weight when it is doing nothing at all.

Seeding runs under the DEK carried by the login token (patterns and amounts are
encrypted columns), so the rows are readable by the request thread — the same
path production uses.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from jose import jwt

from app.core import user_crypto
from app.core.config import get_settings
from app.models import Account, BankConnection, CategoryRule, Transaction, User

SECRET = get_settings().secret_key


def _setup(client, db_session, email="rules@example.com"):
    client.post("/api/v1/auth/register", json={"email": email, "password": "securepassword123"})
    token = client.post(
        "/api/v1/auth/login", data={"username": email, "password": "securepassword123"}
    ).json()["access_token"]
    dek = user_crypto.unwrap_session_dek(jwt.decode(token, SECRET, algorithms=["HS256"])["dk"])
    client.headers["Authorization"] = f"Bearer {token}"
    user = db_session.query(User).filter(User.email == email).first()
    return user, user_crypto.current_dek.set(dek)


def _seed(db, user_id, rules, txns):
    conn = BankConnection(
        user_id=user_id, provider_id="ob-impact", provider_name="Test Bank",
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
    for desc, amount in txns:
        db.add(Transaction(
            account_id=acc.id, external_id=f"tx-{uuid.uuid4()}", transaction_type="debit",
            amount=Decimal(str(amount)), currency="GBP", description=desc, merchant_name=desc,
            transaction_date=datetime(2026, 7, 10, tzinfo=timezone.utc),
        ))
    for pattern, match_type, category in rules:
        db.add(CategoryRule(
            user_id=user_id, pattern=pattern, match_type=match_type, match_field="any",
            category=category, source="manual", enabled=True,
        ))
    db.commit()


def test_reports_matched_effective_and_gaps(client, db_session):
    user, ctx = _setup(client, db_session)
    try:
        _seed(
            db_session, user.id,
            rules=[("TESCO", "contains", "Groceries")],
            txns=[("TESCO METRO", 20), ("TESCO PAYAT PUMP", 55), ("GREGGS PLC", 3)],
        )
    finally:
        user_crypto.current_dek.reset(ctx)

    body = client.get("/api/v1/rules/impact").json()
    assert body["total_transactions"] == 3

    rule = body["rules"][0]
    assert rule["matched"] == 2 and rule["effective"] == 2
    assert float(rule["matched_amount"]) == 75.0
    assert rule["shadowed"] is False and rule["dead"] is False

    # The uncovered transaction becomes a rule candidate.
    assert body["uncategorized_transactions"] == 1
    assert body["gaps"][0]["merchant"] == "GREGGS PLC"
    assert float(body["gaps"][0]["total"]) == 3.0


def test_shadowed_rule_matches_but_decides_nothing(client, db_session):
    """Two rules hit the same transaction; only the winner is effective. The
    loser is the one worth deleting, and `matched` alone would hide that."""
    user, ctx = _setup(client, db_session, email="shadow@example.com")
    try:
        _seed(
            db_session, user.id,
            rules=[
                ("TESCO METRO", "exact", "Groceries"),   # more specific -> wins
                ("TESCO", "contains", "Shopping"),
            ],
            txns=[("TESCO METRO", 20)],
        )
    finally:
        user_crypto.current_dek.reset(ctx)

    by_pattern = {r["pattern"]: r for r in client.get("/api/v1/rules/impact").json()["rules"]}
    assert by_pattern["TESCO METRO"]["effective"] == 1
    loser = by_pattern["TESCO"]
    assert loser["matched"] == 1 and loser["effective"] == 0
    assert loser["shadowed"] is True


def test_dead_rule_is_flagged(client, db_session):
    user, ctx = _setup(client, db_session, email="dead@example.com")
    try:
        _seed(
            db_session, user.id,
            rules=[("NEVER_MATCHES_ANYTHING", "contains", "Misc")],
            txns=[("TESCO METRO", 20)],
        )
    finally:
        user_crypto.current_dek.reset(ctx)

    rule = client.get("/api/v1/rules/impact").json()["rules"][0]
    assert rule["dead"] is True and rule["matched"] == 0


def test_requires_authentication(client):
    assert client.get("/api/v1/rules/impact").status_code == 401
