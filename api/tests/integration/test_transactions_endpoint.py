"""The filtered transactions endpoint: server-side filters, excluded_reason
parity with the spending aggregates, pagination, and user scoping.

Filtering happens in Python after decryption (description/merchant/amount are
encrypted columns); these tests exercise the endpoint through the API so the
DEK flows from the bearer token, exactly as in production.
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from jose import jwt

from app.core import user_crypto
from app.core.config import get_settings
from app.models import Account, BankConnection, Transaction, User
from app.services import analytics_service

SECRET = get_settings().secret_key


def _register(client, email="tx@example.com", password="securepassword123"):
    res = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert res.status_code == 201


def _login(client, email="tx@example.com", password="securepassword123"):
    res = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert res.status_code == 200
    return res.json()["access_token"]


def _dek_from_token(access_token: str) -> bytes:
    payload = jwt.decode(access_token, SECRET, algorithms=["HS256"])
    return user_crypto.unwrap_session_dek(payload["dk"])


def _account(db, user_id, atype="TRANSACTION", name="Current", balance="1000"):
    conn = BankConnection(
        user_id=user_id, provider_id=f"ob-{name}", provider_name="Test Bank",
        access_token="t", refresh_token="r",
    )
    db.add(conn)
    db.flush()
    acc = Account(
        user_id=user_id, bank_connection_id=conn.id,
        external_id=f"ext-{name}-{uuid.uuid4()}", provider_name="Test Bank",
        account_type=atype, display_name=name, current_balance=Decimal(balance),
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


def _tx(db, account, amount, when: date, ttype="debit", merchant="Acme", category=None):
    t = Transaction(
        account_id=account.id, external_id=f"tx-{uuid.uuid4()}",
        transaction_type=ttype, amount=Decimal(str(amount)), currency="GBP",
        description=merchant, merchant_name=merchant, category=category,
        transaction_date=datetime.combine(when, datetime.min.time(), tzinfo=timezone.utc),
    )
    db.add(t)
    db.commit()
    return t


def _setup(client, db_session):
    """Register + login, then seed accounts/transactions under the token's DEK."""
    _register(client)
    token = _login(client)
    dek = _dek_from_token(token)
    client.headers["Authorization"] = f"Bearer {token}"
    user = db_session.query(User).first()
    ctx = user_crypto.current_dek.set(dek)
    return user, ctx


class TestTransactionFilters:
    def test_search_category_amount_and_type_filters(self, client, db_session):
        user, ctx = _setup(client, db_session)
        try:
            acc = _account(db_session, user.id)
            _tx(db_session, acc, 54.20, date(2026, 7, 1), merchant="Tesco", category="Groceries")
            _tx(db_session, acc, 8.10, date(2026, 7, 2), merchant="TfL", category="Transport")
            _tx(db_session, acc, 2500, date(2026, 7, 3), ttype="credit", merchant="Salary")
        finally:
            user_crypto.current_dek.reset(ctx)

        res = client.get("/api/v1/banking/transactions", params={"search": "tesco"})
        items = res.json()["items"]
        assert [i["merchant_name"] for i in items] == ["Tesco"]

        res = client.get("/api/v1/banking/transactions", params={"category": ["Transport"]})
        assert [i["merchant_name"] for i in res.json()["items"]] == ["TfL"]

        res = client.get(
            "/api/v1/banking/transactions", params={"min_amount": 50, "type": "debit"}
        )
        assert [i["merchant_name"] for i in res.json()["items"]] == ["Tesco"]

        res = client.get("/api/v1/banking/transactions", params={"type": "credit"})
        assert [i["merchant_name"] for i in res.json()["items"]] == ["Salary"]

    def test_excluded_reason_matches_spending_aggregates(self, client, db_session):
        """The list's noise labels and the aggregates' exclusions are the same
        transactions — a transfer pair never counts as spending and always
        carries excluded_reason."""
        user, ctx = _setup(client, db_session)
        try:
            a = _account(db_session, user.id, name="Current")
            b = _account(db_session, user.id, atype="SAVINGS", name="Savings")
            # An internal transfer: same amount, opposite types, 2 accounts.
            _tx(db_session, a, 500, date(2026, 7, 1), ttype="debit", merchant="Transfer out")
            _tx(db_session, b, 500, date(2026, 7, 2), ttype="credit", merchant="Transfer in")
            # A card-settling debit.
            _tx(db_session, a, 200, date(2026, 7, 3), merchant="AMEX PAYMENT")
            # Real spending.
            _tx(db_session, a, 30, date(2026, 7, 4), merchant="Deliveroo")

            spending = analytics_service.get_spending(
                db_session, user, period="custom",
                frm=date(2026, 7, 1), to=date(2026, 7, 31), lens="purchases",
            )
        finally:
            user_crypto.current_dek.reset(ctx)

        # Aggregates: only the real purchase counts.
        assert float(spending["total_spent"]) == 30.0

        res = client.get("/api/v1/banking/transactions", params={"page_size": 50})
        by_merchant = {i["merchant_name"]: i for i in res.json()["items"]}
        assert by_merchant["Transfer out"]["excluded_reason"] == "internal_transfer"
        assert by_merchant["Transfer in"]["excluded_reason"] == "internal_transfer"
        assert by_merchant["AMEX PAYMENT"]["excluded_reason"] == "card_payment"
        assert by_merchant["Deliveroo"]["excluded_reason"] is None

        # include_excluded=false leaves exactly the real spending (+ nothing).
        res = client.get(
            "/api/v1/banking/transactions", params={"include_excluded": "false"}
        )
        assert [i["merchant_name"] for i in res.json()["items"]] == ["Deliveroo"]

    def test_nothing_hidden_by_default_and_granular_opt_in_hides(self, client, db_session):
        """The list shows everything by default; each exclusion is opt-in and
        independent (hiding transfers must not hide card payments)."""
        user, ctx = _setup(client, db_session)
        try:
            a = _account(db_session, user.id, name="Current")
            b = _account(db_session, user.id, atype="SAVINGS", name="Savings")
            _tx(db_session, a, 500, date(2026, 7, 1), ttype="debit", merchant="Transfer out")
            _tx(db_session, b, 500, date(2026, 7, 2), ttype="credit", merchant="Transfer in")
            _tx(db_session, a, 200, date(2026, 7, 3), merchant="AMEX PAYMENT")
            _tx(db_session, a, 30, date(2026, 7, 4), merchant="Deliveroo")
        finally:
            user_crypto.current_dek.reset(ctx)

        # Default: everything shown, including the transfer pair and card payment.
        names = lambda p: {i["merchant_name"] for i in client.get("/api/v1/banking/transactions", params=p).json()["items"]}
        assert names({}) == {"Transfer out", "Transfer in", "AMEX PAYMENT", "Deliveroo"}

        # Hiding transfers drops only the transfer pair.
        assert names({"hide_transfers": "true"}) == {"AMEX PAYMENT", "Deliveroo"}

        # Hiding card payments drops only the card payment.
        assert names({"hide_card_payments": "true"}) == {"Transfer out", "Transfer in", "Deliveroo"}

        # Both opt-ins together leave just the real spend.
        assert names({"hide_transfers": "true", "hide_card_payments": "true"}) == {"Deliveroo"}

    def test_pagination_and_sorting(self, client, db_session):
        user, ctx = _setup(client, db_session)
        try:
            acc = _account(db_session, user.id)
            for i in range(5):
                _tx(db_session, acc, 10 * (i + 1), date(2026, 7, i + 1), merchant=f"Shop{i}")
        finally:
            user_crypto.current_dek.reset(ctx)

        res = client.get(
            "/api/v1/banking/transactions",
            params={"page": 2, "page_size": 2, "sort": "amount", "sort_dir": "desc"},
        )
        body = res.json()
        assert body["total"] == 5
        assert [float(i["amount"]) for i in body["items"]] == [30.0, 20.0]

    def test_facets_and_user_scoping(self, client, db_session):
        user, ctx = _setup(client, db_session)
        try:
            acc = _account(db_session, user.id)
            _tx(db_session, acc, 12, date(2026, 7, 1), merchant="Netflix", category="Subscriptions")
            _tx(db_session, acc, 54, date(2026, 7, 2), merchant="Tesco", category="Groceries")
        finally:
            user_crypto.current_dek.reset(ctx)

        res = client.get("/api/v1/banking/transactions/facets")
        body = res.json()
        assert body["categories"] == ["Groceries", "Subscriptions"]
        assert body["merchants"] == ["Netflix", "Tesco"]

        # A second user sees none of it.
        client.headers.pop("Authorization")
        _register(client, email="other@example.com")
        token2 = _login(client, email="other@example.com")
        client.headers["Authorization"] = f"Bearer {token2}"
        res = client.get("/api/v1/banking/transactions")
        assert res.json()["total"] == 0
        res = client.get("/api/v1/banking/transactions/facets")
        assert res.json() == {"categories": [], "merchants": []}


class TestCountsAsPatch:
    def test_patch_sets_and_clears_the_override(self, client, db_session):
        user, ctx = _setup(client, db_session)
        acc = _account(db_session, user.id)
        tx = _tx(db_session, acc, 500, date.today() - timedelta(days=2), merchant="Vanguard")

        # Mark it a transfer → the list labels it and the override is echoed.
        res = client.patch(f"/api/v1/banking/transactions/{tx.id}", json={"counts_as": "transfer"})
        assert res.status_code == 200
        assert res.json()["counts_as_override"] == "transfer"
        items = client.get("/api/v1/banking/transactions").json()["items"]
        mine = next(i for i in items if i["id"] == str(tx.id))
        assert mine["excluded_reason"] == "internal_transfer"

        # Explicit null clears it back to automatic.
        res = client.patch(f"/api/v1/banking/transactions/{tx.id}", json={"counts_as": None})
        assert res.status_code == 200
        assert res.json()["counts_as_override"] is None
        items = client.get("/api/v1/banking/transactions").json()["items"]
        mine = next(i for i in items if i["id"] == str(tx.id))
        assert mine["excluded_reason"] is None

        # An invalid value is rejected.
        res = client.patch(f"/api/v1/banking/transactions/{tx.id}", json={"counts_as": "nonsense"})
        assert res.status_code == 422
        user_crypto.current_dek.reset(ctx)


class TestHoldingsLinkEndpoints:
    def test_link_prices_the_asset_and_unlink_keeps_history(self, client, db_session, monkeypatch):
        from decimal import Decimal
        from app.models import Asset, AssetValuation, Instrument
        from app.services.pricing import providers, service as pxsvc

        user, ctx = _setup(client, db_session)
        # A manual crypto asset with a placeholder value.
        asset = Asset(user_id=user.id, name="My BTC", asset_type="crypto")
        db_session.add(asset)
        db_session.flush()
        db_session.add(AssetValuation(asset_id=asset.id, value=Decimal("1"), valued_at=pxsvc._today() - timedelta(days=1)))
        inst = Instrument(symbol="BTC", name="Bitcoin", kind="crypto", provider="coingecko", provider_ref="bitcoin", currency="GBP")
        db_session.add(inst)
        db_session.commit()

        monkeypatch.setattr(
            providers, "quote",
            lambda *a: providers.Quote(price_native=Decimal("30000"), price_gbp=Decimal("30000"), as_of=datetime.now(timezone.utc)),
        )

        res = client.post(f"/api/v1/assets/{asset.id}/link", json={"instrument_id": str(inst.id), "units": "0.25"})
        assert res.status_code == 200
        body = res.json()
        assert body["instrument"]["symbol"] == "BTC"
        assert Decimal(str(body["unit_price_gbp"])) == Decimal("30000")
        # today's live valuation = 0.25 x 30000
        today_val = next(v for v in body["valuations"] if v["valued_at"] == pxsvc._today().isoformat())
        assert Decimal(str(today_val["value"])) == Decimal("7500.00")

        # Unlink keeps the valuation history.
        res = client.post(f"/api/v1/assets/{asset.id}/unlink")
        assert res.status_code == 200
        assert res.json()["instrument"] is None
        assert any(v["valued_at"] == pxsvc._today().isoformat() for v in res.json()["valuations"])
        user_crypto.current_dek.reset(ctx)

    def test_instrument_search_upserts(self, client, db_session, monkeypatch):
        from app.services.pricing import providers
        user, ctx = _setup(client, db_session)
        monkeypatch.setattr(providers, "search", lambda q: [
            providers.InstrumentHit(symbol="ETH", name="Ethereum", kind="crypto", provider="coingecko", provider_ref="ethereum", currency="GBP"),
        ])
        res = client.get("/api/v1/instruments/search", params={"q": "eth"})
        assert res.status_code == 200
        assert res.json()[0]["symbol"] == "ETH"
        user_crypto.current_dek.reset(ctx)


class TestHoldingsLiabilityGuard:
    def test_liability_cannot_be_linked(self, client, db_session):
        from app.models import Asset, Instrument
        user, ctx = _setup(client, db_session)
        loan = Asset(user_id=user.id, name="Car loan", asset_type="loan")
        inst = Instrument(symbol="BTC", name="Bitcoin", kind="crypto", provider="coingecko", provider_ref="bitcoin", currency="GBP")
        db_session.add_all([loan, inst])
        db_session.commit()
        res = client.post(f"/api/v1/assets/{loan.id}/link", json={"instrument_id": str(inst.id), "units": "1"})
        assert res.status_code == 400
        user_crypto.current_dek.reset(ctx)
