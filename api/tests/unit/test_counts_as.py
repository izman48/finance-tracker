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
        # A counts_as passed here models a hand-set override (locked).
        counts_as_locked=counts_as is not None,
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
    def _rule(self, db, user, counts_as="transfer"):
        r = CategoryRule(
            user_id=user.id, pattern="Vanguard", match_type="contains",
            match_field="any", category="Investing", counts_as=counts_as,
            source="manual",
        )
        db.add(r)
        db.commit()
        return r

    def test_rule_fills_override_but_never_overwrites_hand_set(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user)
        d = svc._today() - timedelta(days=2)
        auto = _tx(db_session, acc, 500, d, merchant="Vanguard")
        hand = _tx(db_session, acc, 500, d, merchant="Vanguard", counts_as="spending")
        self._rule(db_session, user)

        categorization.apply_rules(db_session, user.id, [auto, hand])
        db_session.commit()
        assert auto.counts_as_override == "transfer"    # filled by the rule
        assert auto.counts_as_locked is False           # …and stays rule-owned
        assert auto.category == "Investing"
        assert hand.counts_as_override == "spending"    # hand-set (locked) wins

    def test_deleting_the_rule_clears_its_stamps_on_the_next_run(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user)
        d = svc._today() - timedelta(days=2)
        tx = _tx(db_session, acc, 500, d, merchant="Vanguard")
        rule = self._rule(db_session, user)
        categorization.apply_rules(db_session, user.id, [tx])
        db_session.commit()
        assert tx.counts_as_override == "transfer"

        db_session.delete(rule)
        db_session.commit()
        categorization.apply_rules_to_all(db_session, user.id)
        db_session.commit()
        # No rule claims it anymore → back to automatic, not stuck stale.
        assert tx.counts_as_override is None

    def test_hand_categorized_transactions_still_receive_counts_as(self, db_session):
        """category_locked protects the category, not the counts_as — the
        user's most-curated transactions must not stay polluted."""
        user = _user(db_session)
        acc = _account(db_session, user)
        d = svc._today() - timedelta(days=2)
        tx = _tx(db_session, acc, 500, d, merchant="Vanguard")
        tx.category = "My custom"
        tx.category_locked = True
        db_session.commit()
        self._rule(db_session, user)

        categorization.apply_rules_to_all(db_session, user.id)
        db_session.commit()
        assert tx.counts_as_override == "transfer"  # counts_as applied
        assert tx.category == "My custom"           # category untouched
