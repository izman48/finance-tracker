"""Cost bound for the search (sec, T-07-6): 20,000 transactions over two
years, searched across the maximum window, well inside the MCP client's 60 s
timeout. The whole window is decrypted per call, so this is the worst case."""
import time
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.core import user_crypto
from app.models import Account, BankConnection, Transaction, User
from app.services.transaction_search import london_today
from tests.integration.test_oauth import _bearer
from tests.integration.test_transaction_search import URL, _signup
from tests.integration.test_transactions_endpoint import _dek_from_token

ROWS = 20_000
BUDGET_SECONDS = 20  # a third of the MCP client's 60 s timeout


def test_search_over_20k_rows_and_two_years_is_fast(client, db_session):
    token = _signup(client, "cost@example.com")
    user = db_session.query(User).filter(User.email == "cost@example.com").one()
    ctx = user_crypto.current_dek.set(_dek_from_token(token))
    try:
        conn = BankConnection(user_id=user.id, provider_id="ob-x", provider_name="Bank", access_token="t", refresh_token="r")
        db_session.add(conn)
        db_session.flush()
        acc = Account(user_id=user.id, bank_connection_id=conn.id, external_id=f"e-{uuid.uuid4()}",
                      provider_name="Bank", account_type="TRANSACTION", display_name="Cur", current_balance=Decimal(0))
        db_session.add(acc)
        db_session.flush()
        now = datetime.now(timezone.utc)
        db_session.add_all(
            Transaction(
                account_id=acc.id, external_id=f"t-{i}", transaction_type="debit",
                amount=Decimal("1.00"), currency="GBP",
                description="TESCO STORES" if i % 100 == 0 else f"SHOP {i % 500}",
                merchant_name=None, transaction_date=now - timedelta(minutes=52 * i),  # ~2 years
            )
            for i in range(ROWS)
        )
        db_session.commit()
    finally:
        user_crypto.current_dek.reset(ctx)

    to = london_today()  # the newest row is 'now', which may already be tomorrow in London
    started = time.perf_counter()
    r = client.post(URL, json={"query": "tesco", "frm": (to - timedelta(days=731)).isoformat(), "to": to.isoformat()},
                    headers=_bearer(token))
    elapsed = time.perf_counter() - started
    print(f"\nsearch over {ROWS} rows: {elapsed:.2f}s")
    assert r.status_code == 200, r.text
    assert r.json()["total"] == ROWS // 100
    assert elapsed < BUDGET_SECONDS
