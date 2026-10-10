"""POST /banking/transactions/search: exact, read-only purchase search (T-07-6).

Merchant and description are encrypted, so the route decrypts every row in
the date window and matches in Python. These tests go through the API so the
DEK flows from the bearer token, as in production, and cover sec's criteria:
authz on the API, literal input, London-day boundaries, paging, an exact
Decimal total across pages, the item shape, and a per-user rate limit.
"""
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core import user_crypto
from app.models import Account, BankConnection, OAuthGrant, Transaction, User
from app.services import transaction_search as search
from tests.integration.test_oauth import READ, WRITE, _bearer, _connect, _refresh
from tests.integration.test_transactions_endpoint import _dek_from_token

URL = "/api/v1/banking/transactions/search"


def _signup(client, email):
    client.post("/api/v1/auth/register", json={"email": email, "password": "securepassword123"})
    token = client.post(
        "/api/v1/auth/login", data={"username": email, "password": "securepassword123"}
    ).json()["access_token"]
    return token


def _seed(db, token, email, rows):
    """rows: (merchant, amount, utc datetime, ttype, account_type)."""
    user = db.query(User).filter(User.email == email).one()
    ctx = user_crypto.current_dek.set(_dek_from_token(token))
    try:
        conn = BankConnection(user_id=user.id, provider_id="ob-x", provider_name="Bank", access_token="t", refresh_token="r")
        db.add(conn)
        db.flush()
        accounts = {}
        for merchant, amount, when, ttype, atype in rows:
            if atype not in accounts:
                acc = Account(
                    user_id=user.id, bank_connection_id=conn.id, external_id=f"e-{uuid.uuid4()}",
                    provider_name="Bank", account_type=atype, display_name=atype, current_balance=Decimal("0"),
                )
                db.add(acc)
                db.flush()
                accounts[atype] = acc
            db.add(Transaction(
                account_id=accounts[atype].id, external_id=f"t-{uuid.uuid4()}",
                transaction_type=ttype, amount=Decimal(amount), currency="GBP",
                description=merchant, merchant_name=None, transaction_date=when,
            ))
        db.commit()
        return user, accounts
    finally:
        user_crypto.current_dek.reset(ctx)


def _at(d: date, hour=12, minute=0):
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=timezone.utc)


TODAY = datetime.now(timezone.utc).date()
DAY = TODAY - timedelta(days=5)


def _row(merchant, amount="10.00", when=None, ttype="debit", atype="TRANSACTION"):
    return (merchant, amount, when or _at(DAY), ttype, atype)


def _search(client, token, **body):
    return client.post(URL, json=body, headers=_bearer(token))


@pytest.fixture
def web(client, db_session):
    token = _signup(client, "s@example.com")
    _seed(db_session, token, "s@example.com", [
        _row("TESCO STORES 3297", "12.40"),
        _row("Tesco Express", "3.15"),
        _row("POS TESCO*STORES ON 01 OCT", "40.00"),
        _row("Tesco refund", "5.00", ttype="credit"),
        _row("Sainsbury's", "20.00"),
    ])
    return token


class TestMatching:
    def test_case_insensitive_and_descriptor_variants(self, client, web):
        r = _search(client, web, query="tesco stores")
        assert r.status_code == 200, r.text
        names = sorted(i["description"] for i in r.json()["items"])
        assert names == ["POS TESCO*STORES ON 01 OCT", "TESCO STORES 3297"]

    def test_plain_substring(self, client, web):
        r = _search(client, web, query="TeScO")
        assert r.json()["total"] == 4

    def test_total_amount_is_debits_minus_credits_as_a_string(self, client, web):
        body = _search(client, web, query="tesco").json()
        assert body["total_amount"] == "50.55"  # 12.40 + 3.15 + 40.00 - 5.00

    @pytest.mark.parametrize("special", [".*", "%", "_", "(", "\\"])
    def test_special_characters_match_only_themselves(self, client, db_session, special):
        token = _signup(client, "lit@example.com")
        _seed(db_session, token, "lit@example.com", [
            # What each character would match as a wildcard or regex.
            _row(f"AB{special}CD"), _row("ABXCD"), _row("ABXXCD"), _row("ABCD"),
        ])
        r = _search(client, token, query=f"AB{special}CD")
        assert r.status_code == 200, r.text
        assert [i["description"] for i in r.json()["items"]] == [f"AB{special}CD"]


class TestTransfersAndCardPayments:
    @pytest.fixture
    def token(self, client, db_session):
        token = _signup(client, "t@example.com")
        _seed(db_session, token, "t@example.com", [
            _row("Pot transfer", "100.00", ttype="debit", atype="TRANSACTION"),
            _row("Pot transfer", "100.00", ttype="credit", atype="SAVINGS"),
            _row("AMEX payment", "300.00"),
            _row("Pot shop", "7.00"),
        ])
        return token

    def test_excluded_by_default(self, client, token):
        r = _search(client, token, query="pot")
        assert [i["description"] for i in r.json()["items"]] == ["Pot shop"]
        assert _search(client, token, query="amex").json()["total"] == 0

    def test_flag_includes_them(self, client, token):
        r = _search(client, token, query="pot", include_transfers=True)
        assert r.json()["total"] == 3
        assert _search(client, token, query="amex", include_transfers=True).json()["total"] == 1


class TestDates:
    def test_default_window_is_the_last_90_days(self, client, db_session):
        token = _signup(client, "d@example.com")
        _seed(db_session, token, "d@example.com", [
            _row("Old shop", when=_at(TODAY - timedelta(days=120))),
            _row("New shop", when=_at(TODAY - timedelta(days=30))),
        ])
        body = _search(client, token, query="shop").json()
        assert [i["description"] for i in body["items"]] == ["New shop"]
        assert date.fromisoformat(body["to"]) - date.fromisoformat(body["frm"]) == timedelta(days=90)

    def test_london_day_boundaries_in_summer_and_winter(self, client, db_session):
        token = _signup(client, "l@example.com")
        _seed(db_session, token, "l@example.com", [
            # 00:30 BST on 6 Oct = 23:30 UTC on 5 Oct.
            _row("Late summer", when=datetime(2025, 10, 5, 23, 30, tzinfo=timezone.utc)),
            # 23:30 GMT on 5 Dec is 5 Dec in London too.
            _row("Late winter", when=datetime(2025, 12, 5, 23, 30, tzinfo=timezone.utc)),
        ])

        def found(frm, to):
            return [i["description"] for i in _search(client, token, query="late", frm=frm, to=to).json()["items"]]

        assert found("2025-10-06", "2025-10-06") == ["Late summer"]
        assert found("2025-10-05", "2025-10-05") == []
        assert found("2025-12-05", "2025-12-05") == ["Late winter"]
        assert found("2025-12-06", "2025-12-06") == []

    @pytest.mark.parametrize("frm,to", [
        ("2026-02-01", "2026-01-01"),   # frm after to
        ("2023-01-01", "2025-01-02"),   # 732 days
        ("2026-13-01", "2026-12-31"),   # not a date
        ("01/02/2026", "2026-03-01"),   # not YYYY-MM-DD
    ])
    def test_bad_ranges_are_422(self, client, web, frm, to):
        r = _search(client, web, query="tesco", frm=frm, to=to)
        assert r.status_code == 422

    def test_731_days_is_allowed(self, client, web):
        assert _search(client, web, query="tesco", frm="2024-01-01", to="2026-01-01").status_code == 200


class TestQueryValidation:
    @pytest.mark.parametrize("query", ["", " a ", "x" * 101, "tes\x00co", "tes\nco", "   "])
    def test_rejected(self, client, web, query):
        r = _search(client, web, query=query)
        assert r.status_code == 422
        assert "Traceback" not in r.text and "SELECT" not in r.text

    def test_stripped_before_matching(self, client, web):
        assert _search(client, web, query="  tesco  ").json()["total"] == 4


class TestPaging:
    @pytest.fixture
    def token(self, client, db_session):
        token = _signup(client, "p@example.com")
        rows = [_row(f"Cafe {i}", f"{i}.{i:02d}", when=_at(DAY, minute=i)) for i in range(1, 26)]
        rows.append(_row("Cafe refund", "1.99", ttype="credit"))
        _seed(db_session, token, "p@example.com", rows)
        return token

    def test_total_amount_equals_the_sum_of_every_item_on_every_page(self, client, token):
        items, totals = [], set()
        for page in (1, 2, 3):
            body = _search(client, token, query="cafe", page=page, page_size=10).json()
            items += body["items"]
            totals.add((body["total"], body["total_amount"]))
        assert len(items) == 26 and len({i["id"] for i in items}) == 26
        signed = sum(
            (Decimal(str(i["amount"])) * (1 if i["transaction_type"] == "debit" else -1) for i in items),
            Decimal(0),
        )
        assert totals == {(26, str(signed))}

    def test_page_past_the_end_is_empty_with_the_same_totals(self, client, token):
        first = _search(client, token, query="cafe").json()
        past = _search(client, token, query="cafe", page=9).json()
        assert past["items"] == []
        assert (past["total"], past["total_amount"]) == (first["total"], first["total_amount"])

    @pytest.mark.parametrize("bad", [{"page": 0}, {"page_size": 0}, {"page_size": 101}])
    def test_out_of_range_is_422(self, client, token, bad):
        assert _search(client, token, query="cafe", **bad).status_code == 422


class TestShape:
    def test_items_have_exactly_the_recent_transactions_keys(self, client, web):
        listed = client.get("/api/v1/banking/transactions", headers=_bearer(web)).json()["items"][0]
        found = _search(client, web, query="tesco").json()["items"][0]
        assert set(found) == set(listed)


class TestAuthz:
    def test_requires_authentication(self, client):
        assert client.post(URL, json={"query": "tesco"}).status_code == 401

    def test_mcp_read_token_works(self, client):
        _, _, tokens = _connect(client, scopes=[READ])
        r = _search(client, tokens["access_token"], query="tesco")
        assert r.status_code == 200, r.text

    def test_mcp_token_without_read_is_403(self, client):
        _, client_id, first = _connect(client, scopes=[READ, WRITE])
        narrowed = _refresh(client, first["refresh_token"], client_id, scope=WRITE).json()
        assert _search(client, narrowed["access_token"], query="tesco").status_code == 403

    def test_revoked_grant_is_401(self, client, db_session):
        _, _, tokens = _connect(client, scopes=[READ])
        for grant in db_session.query(OAuthGrant).all():
            grant.revoked_at = datetime.now(timezone.utc)
        db_session.commit()
        assert _search(client, tokens["access_token"], query="tesco").status_code == 401

    def test_users_only_see_and_total_their_own_rows(self, client, db_session):
        a = _signup(client, "a@example.com")
        b = _signup(client, "b@example.com")
        _seed(db_session, a, "a@example.com", [_row("Tesco", "10.00")])
        _seed(db_session, b, "b@example.com", [_row("Tesco", "99.00")])
        body = _search(client, a, query="tesco").json()
        assert body["total"] == 1 and body["total_amount"] == "10.00"
        assert body["items"][0]["amount"] == 10.0

    def test_unknown_fields_are_rejected(self, client, web):
        """No account_id or user_id parameter can be smuggled in."""
        assert _search(client, web, query="tesco", user_id=str(uuid.uuid4())).status_code == 422


class TestRateLimit:
    def test_11th_call_in_a_minute_is_429_with_retry_after(self, client, web):
        for _ in range(10):
            assert _search(client, web, query="tesco").status_code == 200
        r = _search(client, web, query="tesco")
        assert r.status_code == 429
        assert int(r.headers["Retry-After"]) >= 1

    def test_each_user_has_their_own_budget(self, client):
        """Every remote call reaches the API from the MCP container's IP, so
        the key must be the user, not the address."""
        a = _signup(client, "ra@example.com")
        b = _signup(client, "rb@example.com")
        for _ in range(10):
            _search(client, a, query="tesco")
        assert _search(client, a, query="tesco").status_code == 429
        assert _search(client, b, query="tesco").status_code == 200


class TestOneSearchInFlightPerUser:
    """A looping agent must not run several decrypt-everything scans at once
    (sec): a second search from the same user while one runs is 429."""

    def test_concurrent_search_from_the_same_user_is_429_but_others_proceed(self, client, monkeypatch):
        a = _signup(client, "fa@example.com")
        b = _signup(client, "fb@example.com")
        entered, release = threading.Event(), threading.Event()
        real_matcher = search.matcher

        def blocking_matcher(query):
            if query == "blocker":
                entered.set()
                release.wait(timeout=10)
            return real_matcher(query)

        monkeypatch.setattr(search, "matcher", blocking_matcher)
        first: dict = {}
        worker = threading.Thread(target=lambda: first.update(r=_search(client, a, query="blocker")))
        worker.start()
        try:
            assert entered.wait(timeout=10)
            busy = _search(client, a, query="tesco")
            assert busy.status_code == 429
            assert busy.headers["Retry-After"] == "2"
            assert _search(client, b, query="tesco").status_code == 200
        finally:
            release.set()
            worker.join(timeout=10)
        assert first["r"].status_code == 200
        assert _search(client, a, query="tesco").status_code == 200  # slot released

    def test_a_failed_search_releases_the_slot(self, client, monkeypatch):
        a = _signup(client, "fc@example.com")

        def broken(query):
            raise RuntimeError("boom")

        monkeypatch.setattr(search, "matcher", broken)
        with pytest.raises(RuntimeError):
            _search(client, a, query="tesco")
        monkeypatch.undo()
        assert _search(client, a, query="tesco").status_code == 200


class TestPunctuationVariants:
    def test_a_query_with_punctuation_also_matches_the_spaced_variant(self, client, db_session):
        """Pinned on purpose: punctuation folds to spaces on both sides, so
        "AB.*CD" finds the descriptor variant "AB CD", but never "ABXCD"."""
        token = _signup(client, "pv@example.com")
        _seed(db_session, token, "pv@example.com", [_row("AB CD"), _row("ABXCD")])
        found = [i["description"] for i in _search(client, token, query="AB.*CD").json()["items"]]
        assert found == ["AB CD"]
