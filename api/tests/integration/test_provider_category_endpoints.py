"""The endpoints behind the MCP `spending` and `search_transactions` tools
never show a raw provider type as a category (T-08-1).

Transactions arrive through the real sync route (TrueLayer's transaction fetch
stubbed), so the DEK flows from the bearer token as in production.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from jose import jwt

from app.core import user_crypto
from app.core.config import get_settings
from app.models import Account, BankConnection, User
from app.services.categorization import PROVIDER_TRANSACTION_TYPES
from app.services.truelayer import truelayer_service

EMAIL, PASSWORD = "categories@example.com", "securepassword123"


def _tl(n, tx_type, category):
    return {
        "transaction_id": f"tl-ep-{n}",
        "transaction_type": tx_type,
        "transaction_category": category,
        "amount": 10.0,
        "currency": "GBP",
        "description": f"Payee {n}",
        "timestamp": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
    }


@pytest.fixture
def synced_client(client, db_session, monkeypatch):
    client.post("/api/v1/auth/register", json={"email": EMAIL, "password": PASSWORD})
    token = client.post(
        "/api/v1/auth/login", data={"username": EMAIL, "password": PASSWORD}
    ).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    dek = user_crypto.unwrap_session_dek(
        jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])["dk"]
    )
    user = db_session.query(User).filter(User.email == EMAIL).first()
    ctx = user_crypto.current_dek.set(dek)
    try:
        conn = BankConnection(
            user_id=user.id, provider_id="ob-test", provider_name="TEST",
            access_token="access", refresh_token="refresh",
            token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        db_session.add(conn)
        db_session.commit()
        db_session.add(Account(
            user_id=user.id, bank_connection_id=conn.id, external_id="acc-ep",
            provider_name="Test", account_type="TRANSACTION", display_name="Current",
            current_balance=Decimal("1000"),
        ))
        db_session.commit()
    finally:
        user_crypto.current_dek.reset(ctx)

    feed = [
        _tl(i, tx_type, raw)
        for i, (raw, tx_type) in enumerate(
            (raw, t) for raw in sorted(PROVIDER_TRANSACTION_TYPES) for t in ("DEBIT", "CREDIT")
        )
    ]

    async def fake_get_transactions(*_args, **_kwargs):
        return feed

    monkeypatch.setattr(truelayer_service, "get_transactions", fake_get_transactions)
    synced = client.post("/api/v1/banking/sync/transactions", json={"days": 30})
    assert synced.status_code == 200, synced.text
    return client


def test_spending_breakdown_has_no_raw_type(synced_client):
    body = synced_client.get("/api/v1/analytics/spending", params={"period": "last_30"}).json()
    categories = {c["category"] for c in body["by_category"]}
    assert categories  # precondition: the breakdown is populated
    assert not categories & PROVIDER_TRANSACTION_TYPES


def test_search_results_have_no_raw_type(synced_client):
    body = synced_client.post(
        "/api/v1/banking/transactions/search", json={"query": "Payee", "include_transfers": True}
    ).json()
    categories = {item["category"] for item in body["items"]}
    assert body["total"] == 2 * len(PROVIDER_TRANSACTION_TYPES)  # precondition
    assert categories <= {"Income", "Transfers", None}
