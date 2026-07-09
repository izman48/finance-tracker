"""The counts_as override: the user's word beats automatic noise detection.

Transfers to unconnected destinations (ISA direct debits, savings elsewhere)
have no visible incoming leg, so pair-detection reads them as spending. The
override — per transaction, or via a rule's counts_as — must flow through
every consumer: both spending lenses, the trend (and so the projection's
derived surplus), and the list's excluded_reason labels.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from app.models import Account, AccountSetting, CategoryRule, Transaction, User
from app.services import analytics_service as svc
from app.services import categorization


def _user(db):
    u = User(email=f"ca-{datetime.now().timestamp()}@e.com", hashed_password="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _account(db, user, atype="TRANSACTION", name="Cur"):
    a = Account(
        user_id=user.id, bank_connection_id=user.id,
        external_id=f"ext-{name}-{datetime.now().timestamp()}",
        provider_name="Test", account_type=atype, display_name=name,
        current_balance=Decimal("1000"),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _tx(db, account, amount, when, ttype="debit", merchant="Acme", counts_as=None):
    t = Transaction(
        account_id=account.id,
        external_id=f"tx-{merchant}-{when.isoformat()}-{amount}-{datetime.now().timestamp()}",
        transaction_type=ttype, amount=Decimal(str(amount)), currency="GBP",
        description=merchant, merchant_name=merchant,
        transaction_date=datetime.combine(when, datetime.min.time(), tzinfo=timezone.utc),
        counts_as_override=counts_as,
    )
    db.add(t)
    db.commit()
    return t


def _spending(db, user, **kw):
    today = svc._today()
    return svc.get_spending(
        db, user, period="custom", frm=today - timedelta(days=10), to=today, **kw
    )


class TestTransferOverride:
    def test_marked_transfer_leaves_purchases_and_trend(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user)
        d = svc._today() - timedelta(days=2)
        _tx(db_session, acc, 60, d, merchant="Tesco")
        _tx(db_session, acc, 500, d, merchant="Vanguard", counts_as="transfer")

        p = _spending(db_session, user, lens="purchases")
        assert p["total_spent"] == Decimal("60")  # the ISA DD no longer counts
        assert all(m["merchant"] != "Vanguard" for m in p["top_merchants"])

        t = svc.get_spending_trend(db_session, user, months=1)
        assert t["months"][-1]["total"] == Decimal("60")

    def test_money_out_composition_moves_it_to_transfers(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user)
        d = svc._today() - timedelta(days=2)
        _tx(db_session, acc, 500, d, merchant="Vanguard", counts_as="transfer")
        mo = _spending(db_session, user, lens="money_out")
        # Money out still shows it (cash left the bank) but names it a transfer.
        assert mo["total_spent"] == Decimal("500")
        assert mo["composition"]["transfers"] == Decimal("500")

    def test_spending_override_forces_a_detected_pair_leg_to_count(self, db_session):
        user = _user(db_session)
        a = _account(db_session, user, name="A")
        b = _account(db_session, user, atype="SAVINGS", name="B")
        d = svc._today() - timedelta(days=2)
        # A matched pair the detector would exclude…
        out = _tx(db_session, a, 200, d, merchant="Move")
        _tx(db_session, b, 200, d, ttype="credit", merchant="Move")
        p0 = _spending(db_session, user, lens="purchases")
        assert p0["total_spent"] == Decimal("0")
        # …until the user says the debit leg was real spending.
        out.counts_as_override = "spending"
        db_session.commit()
        p1 = _spending(db_session, user, lens="purchases")
        assert p1["total_spent"] == Decimal("200")


class TestCardPaymentOverride:
    def test_unrecognised_repayment_marked_by_hand(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user)
        d = svc._today() - timedelta(days=2)
        # "PAYMENT REF 123" matches no indicator — counted as spending by default.
        _tx(db_session, acc, 300, d, merchant="PAYMENT REF 123")
        assert _spending(db_session, user, lens="purchases")["total_spent"] == Decimal("300")

        db_session.query(Transaction).update({"counts_as_override": "card_payment"})
        db_session.commit()
        p = _spending(db_session, user, lens="purchases")
        assert p["total_spent"] == Decimal("0")
        mo = _spending(db_session, user, lens="money_out")
        assert mo["composition"]["card_repayments"] == Decimal("300")


class TestListLabels:
    def test_classify_noise_reflects_overrides(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user)
        d = svc._today() - timedelta(days=2)
        isa = _tx(db_session, acc, 500, d, merchant="Vanguard", counts_as="transfer")
        # An indicator-matched repayment the user re-marks as real spending.
        forced = _tx(db_session, acc, 40, d, merchant="AMEX payment", counts_as="spending")
        reasons = svc.classify_noise([isa, forced], {acc.id: svc.default_role(acc)})
        assert reasons.get(isa.id) == "internal_transfer"
        assert forced.id not in reasons


class TestRuleCountsAs:
    def test_rule_fills_override_but_never_overwrites_hand_set(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user)
        d = svc._today() - timedelta(days=2)
        auto = _tx(db_session, acc, 500, d, merchant="Vanguard")
        hand = _tx(db_session, acc, 500, d, merchant="Vanguard", counts_as="spending")
        db_session.add(CategoryRule(
            user_id=user.id, pattern="Vanguard", match_type="contains",
            match_field="any", category="Investing", counts_as="transfer",
            source="manual",
        ))
        db_session.commit()

        categorization.apply_rules(db_session, user.id, [auto, hand])
        db_session.commit()
        assert auto.counts_as_override == "transfer"   # filled by the rule
        assert auto.category == "Investing"
        assert hand.counts_as_override == "spending"   # hand-set wins
