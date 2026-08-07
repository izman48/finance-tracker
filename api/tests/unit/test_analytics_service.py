"""Unit tests for the cashflow analytics service."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import (
    Account,
    AccountSetting,
    CommitmentRule,
    CommitmentDirection,
    CommitmentStatus,
    PlannedItem,
    RepaymentScheduleItem,
    Transaction,
    User,
)
from app.services import analytics_service as svc


# --------------------------------------------------------------------------- #
# Pure date / repayment helpers
# --------------------------------------------------------------------------- #
class TestRepaymentDates:
    def test_end_of_month_from_midmonth(self):
        s = AccountSetting(repayment_cadence="end_of_month")
        assert svc.next_repayment_date(s, date(2026, 6, 10)) == date(2026, 6, 30)

    def test_end_of_month_rolls_when_past(self):
        s = AccountSetting(repayment_cadence="end_of_month")
        # already the last day -> that day counts as on/after
        assert svc.next_repayment_date(s, date(2026, 6, 30)) == date(2026, 6, 30)

    def test_end_of_month_february(self):
        s = AccountSetting(repayment_cadence="end_of_month")
        assert svc.next_repayment_date(s, date(2026, 2, 15)) == date(2026, 2, 28)

    def test_monthly_on_day(self):
        s = AccountSetting(repayment_cadence="monthly", repayment_day=28)
        assert svc.next_repayment_date(s, date(2026, 6, 10)) == date(2026, 6, 28)
        # past the 28th -> next month
        assert svc.next_repayment_date(s, date(2026, 6, 29)) == date(2026, 7, 28)

    def test_every_n_months(self):
        s = AccountSetting(
            repayment_cadence="every_n_months",
            repayment_interval_months=3,
            repayment_anchor_date=date(2026, 1, 15),
        )
        assert svc.next_repayment_date(s, date(2026, 6, 1)) == date(2026, 7, 15)

    def test_amount_full_vs_fixed(self):
        full = AccountSetting(repayment_strategy="full_balance")
        assert svc.repayment_amount(full, Decimal("900")) == Decimal("900")
        fixed = AccountSetting(repayment_strategy="fixed", repayment_fixed_amount=Decimal("150"))
        assert svc.repayment_amount(fixed, Decimal("900")) == Decimal("150")


class TestCadenceMapping:
    @pytest.mark.parametrize(
        "days,expected",
        [(7, "weekly"), (30, "monthly"), (90, "every_n_months"), (14, "custom_days")],
    )
    def test_cadence_from_interval(self, days, expected):
        cadence, _, _ = svc._cadence_from_interval(days)
        assert cadence == expected


class TestOccurrences:
    def test_monthly_count_over_window(self):
        rule = CommitmentRule(
            direction="expense", label="Rent", amount=Decimal("1200"),
            cadence="monthly", next_date=date(2026, 6, 1),
        )
        occ = svc.commitment_occurrences(rule, date(2026, 6, 1), date(2026, 8, 31))
        assert occ == [date(2026, 6, 1), date(2026, 7, 1), date(2026, 8, 1)]

    def test_skips_past_occurrences(self):
        rule = CommitmentRule(
            direction="income", label="Salary", amount=Decimal("2500"),
            cadence="monthly", next_date=date(2026, 1, 25),
        )
        occ = svc.commitment_occurrences(rule, date(2026, 6, 1), date(2026, 6, 30))
        assert occ == [date(2026, 6, 25)]


# --------------------------------------------------------------------------- #
# DB-backed: detection + summary
# --------------------------------------------------------------------------- #
def _user(db):
    u = User(email=f"a{datetime.now().timestamp()}@e.com", hashed_password="x")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _account(db, user, atype="TRANSACTION", balance="0", name="Acc"):
    a = Account(
        user_id=user.id, bank_connection_id=user.id,  # FK not enforced in sqlite test
        external_id=f"ext-{name}-{datetime.now().timestamp()}",
        provider_name="Test", account_type=atype, display_name=name,
        current_balance=Decimal(balance),
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def _tx(db, account, amount, when, ttype="debit", merchant="Acme"):
    t = Transaction(
        account_id=account.id, external_id=f"tx-{merchant}-{when.isoformat()}",
        transaction_type=ttype, amount=Decimal(str(amount)), currency="GBP",
        description=merchant, merchant_name=merchant,
        transaction_date=datetime.combine(when, datetime.min.time(), tzinfo=timezone.utc),
    )
    db.add(t)
    db.commit()
    return t


class TestDetection:
    def test_detects_monthly_expense_and_income(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user, name="Cur")
        # Anchor to today so the patterns read as still-active (detection
        # skips series whose next occurrence is well overdue).
        base = svc._add_months(date.today(), -3)
        for i in range(4):
            _tx(db_session, acc, 50, svc._add_months(base, i), ttype="debit", merchant="Netflix")
        for i in range(3):
            _tx(db_session, acc, 2500, svc._add_months(base, i), ttype="credit", merchant="Salary")

        found = {(c["direction"], c["label"]): c for c in svc.detect_recurring(db_session, user)}
        assert ("expense", "Netflix") in found
        assert ("income", "Salary") in found
        assert found[("expense", "Netflix")]["cadence"] == "monthly"
        # Surfaced next dates are never in the past.
        assert found[("expense", "Netflix")]["next_date"] >= date.today()

    def test_lapsed_pattern_not_suggested(self, db_session):
        """A series whose next occurrence is months overdue is treated as ended."""
        user = _user(db_session)
        acc = _account(db_session, user, name="Cur")
        base = svc._add_months(date.today(), -9)
        for i in range(4):  # last occurrence ~5 months ago
            _tx(db_session, acc, 9.99, svc._add_months(base, i), ttype="debit", merchant="OldGym")

        found = {c["label"] for c in svc.detect_recurring(db_session, user)}
        assert "OldGym" not in found

    def test_mark_transaction_recurring(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user, name="Cur")
        tx = _tx(db_session, acc, 60, date(2026, 5, 4), ttype="debit", merchant="Tesco")

        rule = svc.commitment_from_transaction(db_session, user, str(tx.id), "monthly")
        assert rule.label == "Tesco"
        assert rule.direction == "expense"
        assert rule.amount == Decimal("60")
        assert rule.status == "confirmed"
        assert rule.next_date > svc._today()

    def test_mark_recurring_dedupes_with_suggestion(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user, name="Cur")
        tx = _tx(db_session, acc, 60, date(2026, 5, 4), ttype="debit", merchant="Tesco")
        # pre-existing suggestion for the same merchant
        db_session.add(CommitmentRule(
            user_id=user.id, direction="expense", label="Tesco", amount=Decimal("55"),
            cadence="monthly", next_date=date(2026, 6, 4),
            status="suggested", match_key="expense:tesco",
        ))
        db_session.commit()

        svc.commitment_from_transaction(db_session, user, str(tx.id), "monthly")
        # label is encrypted at rest — match in Python, not SQL.
        tescos = [r for r in db_session.query(CommitmentRule).all() if r.label == "Tesco"]
        assert len(tescos) == 1          # confirmed the suggestion, didn't duplicate
        assert tescos[0].status == "confirmed"

    def test_ignores_too_few(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user)
        _tx(db_session, acc, 10, date(2026, 1, 1), merchant="OneOff")
        _tx(db_session, acc, 10, date(2026, 2, 1), merchant="OneOff")
        assert svc.detect_recurring(db_session, user) == []


class TestSummary:
    def test_safe_to_spend_excludes_credit_and_subtracts_commitments(self, db_session):
        user = _user(db_session)
        spending = _account(db_session, user, "TRANSACTION", "4200", "Current")
        _account(db_session, user, "CREDIT_CARD", "900", "Amex")

        today = svc._today()
        # Confirmed salary next week -> defines the payday window.
        db_session.add(CommitmentRule(
            user_id=user.id, direction="income", label="Salary", amount=Decimal("2500"),
            cadence="monthly", next_date=today + timedelta(days=7),
            status=CommitmentStatus.CONFIRMED.value,
        ))
        # Confirmed rent due in 3 days (before payday).
        db_session.add(CommitmentRule(
            user_id=user.id, direction="expense", label="Rent", amount=Decimal("1200"),
            cadence="monthly", next_date=today + timedelta(days=3),
            status=CommitmentStatus.CONFIRMED.value,
        ))
        db_session.commit()

        s = svc.get_summary(db_session, user)
        assert s["available_cash"] == Decimal("4200")   # credit card excluded
        assert s["credit_owed"] == Decimal("900")
        assert s["committed_before_payday"] == Decimal("1200")
        assert s["safe_to_spend"] == Decimal("3000")    # 4200 - 1200
        assert s["next_payday"] == today + timedelta(days=7)

    def test_forecast_running_balance_and_breaches(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user, "TRANSACTION", "500", "Current")
        db_session.add(AccountSetting(
            user_id=user.id, account_id=acc.id, role="spending",
            overdraft_limit=Decimal("300"),
        ))
        today = svc._today()
        db_session.add(CommitmentRule(
            user_id=user.id, direction="expense", label="Big bill", amount=Decimal("1000"),
            cadence="monthly", next_date=today + timedelta(days=3),
            status=CommitmentStatus.CONFIRMED.value,
        ))
        db_session.add(CommitmentRule(
            user_id=user.id, direction="income", label="Pay", amount=Decimal("2000"),
            cadence="monthly", next_date=today + timedelta(days=10),
            status=CommitmentStatus.CONFIRMED.value,
        ))
        db_session.commit()

        f = svc.get_forecast(db_session, user, horizon="30")
        assert f["start_balance"] == Decimal("500")
        assert f["min_balance"] == Decimal("-500")          # 500 - 1000
        assert f["min_date"] == today + timedelta(days=3)
        assert f["end_balance"] == Decimal("1500")          # after +2000
        assert "zero" in f["breaches"]
        assert "overdraft" in f["breaches"]                 # -500 < -300 limit

    def test_last_payday_steps_back_from_future_next_date(self, db_session):
        user = _user(db_session)
        today = svc._today()
        db_session.add(CommitmentRule(
            user_id=user.id, direction="income", label="Pay", amount=Decimal("2000"),
            cadence="monthly", next_date=today + timedelta(days=20),
            status=CommitmentStatus.CONFIRMED.value,
        ))
        db_session.commit()
        lp = svc.last_payday(db_session, user, today)
        # one month before next_date, which is <= today
        assert lp is not None and lp <= today
        assert (today + timedelta(days=20) - lp).days in (28, 29, 30, 31)


class TestPaydaySelection:
    """With several incomes, a flagged is_payday income defines payday; with no
    flag, every confirmed income counts (unchanged back-compat)."""

    def _income(self, db, user, label, next_in_days, is_payday=False):
        r = CommitmentRule(
            user_id=user.id, direction="income", label=label, amount=Decimal("2000"),
            cadence="monthly", next_date=svc._today() + timedelta(days=next_in_days),
            status=CommitmentStatus.CONFIRMED.value, is_payday=is_payday,
        )
        db.add(r)
        db.commit()
        return r

    def test_flagged_income_defines_next_payday(self, db_session):
        user = _user(db_session)
        today = svc._today()
        self._income(db_session, user, "Freelance", 3)                 # sooner, not payday
        self._income(db_session, user, "Salary", 20, is_payday=True)   # the payday
        assert svc.next_payday(db_session, user, today) == today + timedelta(days=20)

    def test_flagged_income_defines_last_payday(self, db_session):
        user = _user(db_session)
        today = svc._today()
        self._income(db_session, user, "Freelance", 3)
        self._income(db_session, user, "Salary", 20, is_payday=True)
        lp = svc.last_payday(db_session, user, today)
        assert lp is not None and lp <= today
        # salary's previous occurrence, ~a month before its next date
        assert (today + timedelta(days=20) - lp).days in (28, 29, 30, 31)

    def test_no_flag_falls_back_to_nearest_income(self, db_session):
        user = _user(db_session)
        today = svc._today()
        self._income(db_session, user, "Freelance", 3)
        self._income(db_session, user, "Salary", 20)
        # nothing flagged -> nearest confirmed income wins, as before
        assert svc.next_payday(db_session, user, today) == today + timedelta(days=3)


class TestCreditRepayments:
    def test_flex_installments_recur_monthly(self, db_session):
        user = _user(db_session)
        spending = _account(db_session, user, "TRANSACTION", "5000", "Current")
        flex = _account(db_session, user, "CREDIT_CARD", "900", "Flex")
        db_session.add_all([
            AccountSetting(user_id=user.id, account_id=spending.id, role="spending"),
            AccountSetting(
                user_id=user.id, account_id=flex.id, role="credit",
                repayment_cadence="monthly", repayment_day=15,
                repayment_strategy="installments", repayment_installments=3,
            ),
        ])
        db_session.commit()

        f = svc.get_forecast(db_session, user, horizon="90")
        repays = [e for p in f["timeline"] for e in p["events"] if e["kind"] == "repayment"]
        # 900 over 3 monthly installments -> three -300 payments, not one
        assert len(repays) == 3
        assert all(e["amount"] == Decimal("-300.00") for e in repays)

    def test_full_balance_is_single_payment(self, db_session):
        """Amex pays the current balance once; we don't assume it recurs."""
        user = _user(db_session)
        _account(db_session, user, "TRANSACTION", "5000", "Current")
        amex = _account(db_session, user, "CREDIT_CARD", "400", "Amex")
        db_session.add(AccountSetting(
            user_id=user.id, account_id=amex.id, role="credit",
            repayment_cadence="end_of_month", repayment_strategy="full_balance",
        ))
        db_session.commit()
        f = svc.get_forecast(db_session, user, horizon="90")
        repays = [e for p in f["timeline"] for e in p["events"] if e["kind"] == "repayment"]
        assert len(repays) == 1
        assert repays[0]["amount"] == Decimal("-400.00")

    def test_fixed_pays_down_balance(self, db_session):
        """Fixed amount each cycle until the balance is cleared (last = remainder)."""
        user = _user(db_session)
        _account(db_session, user, "TRANSACTION", "5000", "Current")
        card = _account(db_session, user, "CREDIT_CARD", "500", "Card")
        db_session.add(AccountSetting(
            user_id=user.id, account_id=card.id, role="credit",
            repayment_cadence="every_n_months", repayment_interval_months=1,
            repayment_anchor_date=svc._today() + timedelta(days=10),
            repayment_strategy="fixed", repayment_fixed_amount=Decimal("200"),
        ))
        db_session.commit()
        f = svc.get_forecast(db_session, user, horizon="90")
        repays = [e["amount"] for p in f["timeline"] for e in p["events"] if e["kind"] == "repayment"]
        # 500 at £200/mo -> 200, 200, 100 (totals to the balance)
        assert repays == [Decimal("-200.00"), Decimal("-200.00"), Decimal("-100.00")]


class TestSpendingDrilldown:
    def test_filters_by_kind_category_merchant(self, db_session):
        user = _user(db_session)
        cur = _account(db_session, user, "TRANSACTION", "1000", "Current")
        amex = _account(db_session, user, "CREDIT_CARD", "0", "Amex")
        db_session.add_all([
            AccountSetting(user_id=user.id, account_id=cur.id, role="spending"),
            AccountSetting(user_id=user.id, account_id=amex.id, role="credit"),
        ])
        db_session.commit()
        today = svc._today()
        t1 = _tx(db_session, cur, 60, today - timedelta(days=2), "debit", "Tesco")
        t2 = _tx(db_session, amex, 120, today - timedelta(days=2), "debit", "Amazon")
        t1.category, t2.category = "Groceries", "Shopping"
        db_session.commit()

        alltx = svc.spending_transactions(db_session, user, period="last_30")
        assert {r["merchant"] for r in alltx} == {"Tesco", "Amazon"}
        assert [r["merchant"] for r in svc.spending_transactions(db_session, user, period="last_30", kind="cash")] == ["Tesco"]
        assert [r["merchant"] for r in svc.spending_transactions(db_session, user, period="last_30", kind="credit")] == ["Amazon"]
        assert [r["merchant"] for r in svc.spending_transactions(db_session, user, period="last_30", category="Groceries")] == ["Tesco"]
        assert [r["amount"] for r in svc.spending_transactions(db_session, user, period="last_30", merchant="Amazon")] == [Decimal("120")]

    def test_drilldown_excludes_noise_and_sums_to_breakdown(self, db_session):
        user = _user(db_session)
        cur = _account(db_session, user, "TRANSACTION", "1000", "Current")
        db_session.add(AccountSetting(user_id=user.id, account_id=cur.id, role="spending"))
        db_session.commit()
        today = svc._today()
        _tx(db_session, cur, 60, today - timedelta(days=2), "debit", "Tesco")
        _tx(db_session, cur, 200, today - timedelta(days=1), "debit", "AMEX payment")  # repayment — excluded
        _tx(db_session, cur, 500, today - timedelta(days=1), "credit", "Salary")       # income — excluded

        txns = svc.spending_transactions(db_session, user, period="last_30")
        assert [r["merchant"] for r in txns] == ["Tesco"]
        # the drill-down is exactly the breakdown, itemised
        s = svc.get_spending(db_session, user, period="last_30", lens="purchases")
        assert sum(r["amount"] for r in txns) == s["total_spent"]


class TestScheduledRepayments:
    def test_emits_user_listed_amounts_in_range(self, db_session):
        user = _user(db_session)
        card = _account(db_session, user, "CREDIT_CARD", "5000", "Amex")
        db_session.add(AccountSetting(
            user_id=user.id, account_id=card.id, role="credit",
            repayment_strategy="scheduled",
        ))
        today = svc._today()
        d1, d2 = today + timedelta(days=5), today + timedelta(days=40)
        d_out = today + timedelta(days=400)
        db_session.add_all([
            # added out of order to prove the result is sorted by date
            RepaymentScheduleItem(user_id=user.id, account_id=card.id, due_date=d2, amount=Decimal("900")),
            RepaymentScheduleItem(user_id=user.id, account_id=card.id, due_date=d1, amount=Decimal("2000")),
            RepaymentScheduleItem(user_id=user.id, account_id=card.id, due_date=d_out, amount=Decimal("500")),
        ])
        db_session.commit()

        events = svc.repayment_events(db_session, user, today, today + timedelta(days=92))
        assert [(e["due_date"], e["amount"]) for e in events] == [
            (d1, Decimal("2000")),
            (d2, Decimal("900")),  # the +400d item is out of range and excluded
        ]

    def test_scheduled_amounts_hit_the_forecast(self, db_session):
        user = _user(db_session)
        _account(db_session, user, "TRANSACTION", "5000", "Current")
        card = _account(db_session, user, "CREDIT_CARD", "5000", "Amex")
        db_session.add_all([
            AccountSetting(user_id=user.id, account_id=card.id, role="credit",
                           repayment_strategy="scheduled"),
        ])
        today = svc._today()
        db_session.add_all([
            RepaymentScheduleItem(user_id=user.id, account_id=card.id,
                                  due_date=today + timedelta(days=5), amount=Decimal("2000")),
            RepaymentScheduleItem(user_id=user.id, account_id=card.id,
                                  due_date=today + timedelta(days=40), amount=Decimal("900")),
        ])
        db_session.commit()

        f = svc.get_forecast(db_session, user, horizon="90")
        repays = [e["amount"] for p in f["timeline"] for e in p["events"] if e["kind"] == "repayment"]
        # exactly what the user scheduled, not a balance-derived formula
        assert repays == [Decimal("-2000.00"), Decimal("-900.00")]


class TestPayOnFinance:
    def test_convert_sets_monthly_x_months_and_links_source(self, db_session):
        user = _user(db_session)
        cur = _account(db_session, user, "TRANSACTION", "5000", "Current")
        today = svc._today()
        tx = _tx(db_session, cur, 1200, today - timedelta(days=3), "debit", "Laptop")
        db_session.commit()

        item = svc.convert_transaction_to_plan(
            db_session, user, str(tx.id), months=12,
            monthly_amount=Decimal("110"), start_date=today + timedelta(days=5),
        )
        assert item.installments == 12
        assert item.total_amount == Decimal("1320.00")  # 110 × 12
        assert item.source_transaction_id == tx.id
        assert item.kind == "installment_plan"

        # re-converting the same transaction updates, never duplicates
        item2 = svc.convert_transaction_to_plan(
            db_session, user, str(tx.id), months=6,
            monthly_amount=Decimal("200"), start_date=today + timedelta(days=5),
        )
        assert item2.id == item.id and item2.installments == 6
        assert db_session.query(PlannedItem).filter(
            PlannedItem.source_transaction_id == tx.id
        ).count() == 1

    def test_financed_purchase_excluded_from_spending(self, db_session):
        user = _user(db_session)
        cur = _account(db_session, user, "TRANSACTION", "5000", "Current")
        db_session.add(AccountSetting(user_id=user.id, account_id=cur.id, role="spending"))
        today = svc._today()
        big = _tx(db_session, cur, 1200, today - timedelta(days=3), "debit", "Laptop")
        _tx(db_session, cur, 60, today - timedelta(days=2), "debit", "Tesco")
        db_session.commit()

        assert svc.get_spending(db_session, user, period="last_30", lens="purchases")["total_spent"] == Decimal("1260")
        svc.convert_transaction_to_plan(
            db_session, user, str(big.id), months=12,
            monthly_amount=Decimal("100"), start_date=today + timedelta(days=5),
        )
        # lump gone; only the Tesco cash purchase remains
        assert svc.get_spending(db_session, user, period="last_30", lens="purchases")["total_spent"] == Decimal("60")

    def test_financed_installments_hit_the_forecast(self, db_session):
        user = _user(db_session)
        cur = _account(db_session, user, "TRANSACTION", "5000", "Current")
        db_session.add(AccountSetting(user_id=user.id, account_id=cur.id, role="spending"))
        today = svc._today()
        tx = _tx(db_session, cur, 600, today - timedelta(days=3), "debit", "Sofa")
        db_session.commit()
        svc.convert_transaction_to_plan(
            db_session, user, str(tx.id), months=3,
            monthly_amount=Decimal("200"), start_date=today + timedelta(days=5),
        )
        f = svc.get_forecast(db_session, user, horizon="90")
        planned = [e for p in f["timeline"] for e in p["events"] if e["kind"] == "planned"]
        assert len(planned) == 3
        assert all(e["amount"] == Decimal("-200.00") for e in planned)


class TestInstallments:
    def test_even_split(self):
        assert svc.installment_amount(600, 3) == Decimal("200.00")

    def test_with_simple_interest(self):
        # 600 * 12% * (3/12) = 18 interest -> 618 / 3 = 206
        assert svc.installment_amount(600, 3, apr=Decimal("12")) == Decimal("206.00")

    def test_with_fee(self):
        assert svc.installment_amount(600, 3, fee=Decimal("30")) == Decimal("210.00")

    def test_planned_installments_hit_the_forecast(self, db_session):
        user = _user(db_session)
        acc = _account(db_session, user, "TRANSACTION", "5000", "Current")
        db_session.add(AccountSetting(user_id=user.id, account_id=acc.id, role="spending"))
        today = svc._today()
        db_session.add(PlannedItem(
            user_id=user.id, name="Laptop", direction="expense", kind="installment_plan",
            start_date=today + timedelta(days=5), total_amount=Decimal("600"),
            installments=3, cadence="monthly",
        ))
        db_session.commit()

        f = svc.get_forecast(db_session, user, horizon="90")
        planned = [e for p in f["timeline"] for e in p["events"] if e["kind"] == "planned"]
        assert len(planned) == 3
        assert all(e["amount"] == Decimal("-200.00") for e in planned)
        # 5000 - 3*200 over the horizon
        assert f["end_balance"] == Decimal("4400.00")


class TestSpending:
    def test_credit_vs_cash_split_and_exclusions(self, db_session):
        user = _user(db_session)
        cur = _account(db_session, user, "TRANSACTION", "1000", "Current")
        amex = _account(db_session, user, "CREDIT_CARD", "200", "Amex")
        db_session.add_all([
            AccountSetting(user_id=user.id, account_id=cur.id, role="spending"),
            AccountSetting(user_id=user.id, account_id=amex.id, role="credit"),
        ])
        db_session.commit()
        today = svc._today()
        # cash purchase, card purchase, a card-repayment (should be excluded)
        _tx(db_session, cur, 60, today - timedelta(days=2), "debit", "Tesco")
        _tx(db_session, amex, 120, today - timedelta(days=2), "debit", "Amazon")
        _tx(db_session, cur, 200, today - timedelta(days=1), "debit", "AMEX payment")

        s = svc.get_spending(db_session, user, period="last_30", lens="purchases")
        assert s["paid_from_cash"] == Decimal("60")        # Tesco only; Amex payment excluded
        assert s["charged_to_credit"] == Decimal("120")    # Amazon
        assert s["total_spent"] == Decimal("180")

    def test_trend_buckets_by_month_excludes_noise(self, db_session):
        user = _user(db_session)
        cur = _account(db_session, user, "TRANSACTION", "1000", "Current")
        amex = _account(db_session, user, "CREDIT_CARD", "0", "Amex")
        db_session.add_all([
            AccountSetting(user_id=user.id, account_id=cur.id, role="spending"),
            AccountSetting(user_id=user.id, account_id=amex.id, role="credit"),
        ])
        db_session.commit()
        today = svc._today()
        this_m = today.replace(day=15) if today.day > 15 else today
        last_m = svc._add_months(this_m, -1)
        _tx(db_session, cur, 100, last_m, "debit", "Tesco")          # cash, last month
        _tx(db_session, cur, 50, this_m, "debit", "Pret")            # cash, this month
        _tx(db_session, amex, 200, this_m, "debit", "Amazon")        # credit, this month
        _tx(db_session, cur, 300, this_m, "debit", "AMEX payment")   # card payment -> excluded
        _tx(db_session, cur, 500, this_m, "credit", "Salary")        # income -> excluded

        t = svc.get_spending_trend(db_session, user, months=3)
        by_month = {m["month"]: m for m in t["months"]}
        assert len(t["months"]) == 3                                  # seeded, incl. empty months
        assert by_month[svc._month_key(last_m)]["total"] == Decimal("100")
        assert by_month[svc._month_key(this_m)]["total"] == Decimal("250")   # 50 + 200, noise gone
        assert by_month[svc._month_key(this_m)]["charged_to_credit"] == Decimal("200")

    def test_suggested_commitments_do_not_count(self, db_session):
        user = _user(db_session)
        _account(db_session, user, "TRANSACTION", "1000", "Current")
        today = svc._today()
        db_session.add(CommitmentRule(
            user_id=user.id, direction="expense", label="Maybe", amount=Decimal("500"),
            cadence="monthly", next_date=today + timedelta(days=2),
            status=CommitmentStatus.SUGGESTED.value,  # not confirmed
        ))
        db_session.commit()
        s = svc.get_summary(db_session, user)
        # No confirmed income -> 30-day default window; suggested expense ignored.
        assert s["committed_before_payday"] == Decimal("0")
        assert s["safe_to_spend"] == Decimal("1000")


class TestMoneyOutLens:
    """The money-out lens: cash that left the bank (incl. card payoffs),
    reconciling and composition-transparent — the default Spending headline."""

    def _seed(self, db):
        user = _user(db)
        cur = _account(db, user, "TRANSACTION", "1000", "Cur")
        card = _account(db, user, "CREDIT_CARD", "-30", "Card")
        d = date(2026, 7, 10)
        _tx(db, cur, 50, d, ttype="debit", merchant="Tesco")    # cash purchase
        _tx(db, cur, 200, d, ttype="debit", merchant="AMEX")    # card payoff (debit on current)
        _tx(db, card, 30, d, ttype="debit", merchant="Coffee")  # purchase ON the card
        return user

    def _win(self, db, user, **kw):
        return svc.get_spending(db, user, period="custom", frm=date(2026, 7, 1), to=date(2026, 7, 31), **kw)

    def test_money_out_counts_bank_debits_including_the_card_payoff(self, db_session):
        user = self._seed(db_session)
        mo = self._win(db_session, user)  # default lens = money_out
        assert mo["lens"] == "money_out"
        # 50 cash purchase + 200 card payoff; the 30 card PURCHASE is not cash out.
        assert float(mo["total_spent"]) == 250.0

    def test_composition_names_whats_inside_and_sums_to_total(self, db_session):
        user = self._seed(db_session)
        c = self._win(db_session, user)["composition"]
        assert float(c["card_repayments"]) == 200.0
        assert float(c["other"]) == 50.0
        assert float(c["transfers"]) == 0.0
        assert float(c["card_repayments"]) + float(c["transfers"]) + float(c["commitments"]) + float(c["other"]) == 250.0

    def test_settlement_paired_across_accounts_is_still_a_card_repayment(self, db_session):
        """Real bank data carries both legs of a payoff: the debit leaving the
        current account and the credit landing on the card. That pair is an
        internal transfer, which used to claim the transaction before the
        card-repayment check ran — leaving card_repayments permanently £0.
        The descriptor is the truncated form banks actually send.
        """
        user = _user(db_session)
        cur = _account(db_session, user, "TRANSACTION", "1000", "Cur")
        card = _account(db_session, user, "CREDIT_CARD", "-200", "Card")
        d = date(2026, 7, 10)
        _tx(db_session, cur, 200, d, ttype="debit",
            merchant="AMERICAN EXP 3773 PB945227708021965 FT")
        _tx(db_session, card, 200, d, ttype="credit", merchant="PAYMENT RECEIVED")

        c = self._win(db_session, user)["composition"]
        assert float(c["card_repayments"]) == 200.0
        assert float(c["transfers"]) == 0.0

    def test_a_genuine_transfer_is_still_a_transfer(self, db_session):
        """The other side of the precedence change: moving money between your
        own current accounts must not be reported as a card repayment."""
        user = _user(db_session)
        a = _account(db_session, user, "TRANSACTION", "1000", "A")
        b = _account(db_session, user, "TRANSACTION", "0", "B")
        d = date(2026, 7, 10)
        # Both legs share a description and date, so _tx_desc is required to
        # keep external_id unique (as a real paired transfer would be).
        _tx_desc(db_session, a, 300, d, ttype="debit", description="IESA WAZEER NEW BANK APP FT")
        _tx_desc(db_session, b, 300, d, ttype="credit", description="IESA WAZEER NEW BANK APP FT")

        c = self._win(db_session, user)["composition"]
        assert float(c["transfers"]) == 300.0
        assert float(c["card_repayments"]) == 0.0

    def test_purchases_lens_excludes_the_payoff_and_has_no_composition(self, db_session):
        user = self._seed(db_session)
        p = self._win(db_session, user, lens="purchases")
        assert float(p["total_spent"]) == 80.0  # 50 cash + 30 card purchase; payoff excluded
        assert p["composition"] is None

    def test_hiding_card_payments_drops_the_payoff_from_money_out(self, db_session):
        user = self._seed(db_session)
        h = self._win(db_session, user, hide_card_payments=True)
        assert float(h["total_spent"]) == 50.0


class TestSpendingScope:
    """account_id / kind scope the category + merchant breakdown to the active
    drill (an account, or the cash/credit side) so the donut tracks the click."""

    def _seed(self, db):
        user = _user(db)
        cur = _account(db, user, "TRANSACTION", "1000", "Cur")
        card = _account(db, user, "CREDIT_CARD", "-30", "Card")
        d = date(2026, 7, 10)
        _tx(db, cur, 60, d, ttype="debit", merchant="Tesco")     # cash purchase
        _tx(db, card, 120, d, ttype="debit", merchant="Amazon")  # card purchase
        return user, cur, card

    def _win(self, db, user, **kw):
        return svc.get_spending(
            db, user, period="custom", frm=date(2026, 7, 1), to=date(2026, 7, 31),
            lens="purchases", **kw,
        )

    def test_kind_credit_scopes_breakdown_to_card_purchases(self, db_session):
        user, _cur, _card = self._seed(db_session)
        s = self._win(db_session, user, kind="credit")
        assert float(s["total_spent"]) == 120.0
        assert {m["merchant"] for m in s["top_merchants"]} == {"Amazon"}

    def test_kind_cash_scopes_breakdown_to_bank_purchases(self, db_session):
        user, _cur, _card = self._seed(db_session)
        s = self._win(db_session, user, kind="cash")
        assert float(s["total_spent"]) == 60.0
        assert {m["merchant"] for m in s["top_merchants"]} == {"Tesco"}

    def test_account_id_scopes_breakdown_to_one_account(self, db_session):
        user, _cur, card = self._seed(db_session)
        s = self._win(db_session, user, account_id=str(card.id))
        assert float(s["total_spent"]) == 120.0
        assert {m["merchant"] for m in s["top_merchants"]} == {"Amazon"}

    def test_unscoped_includes_both_sides(self, db_session):
        user, _cur, _card = self._seed(db_session)
        s = self._win(db_session, user)
        assert float(s["total_spent"]) == 180.0
        assert {m["merchant"] for m in s["top_merchants"]} == {"Tesco", "Amazon"}


class TestSkipCommitment:
    def test_skip_advances_next_occurrence_one_step(self, db_session):
        user = _user(db_session)
        rule = CommitmentRule(
            user_id=user.id, direction="expense", label="Rent", amount=Decimal("1100"),
            cadence="monthly", next_date=date(2026, 7, 1),
            status=CommitmentStatus.CONFIRMED.value,
        )
        db_session.add(rule)
        db_session.commit()
        db_session.refresh(rule)

        out = svc.skip_commitment(db_session, user, str(rule.id))
        assert out is not None
        assert out.next_date == date(2026, 8, 1)  # advanced one month, so July drops out

    def test_skip_works_for_income_too(self, db_session):
        user = _user(db_session)
        rule = CommitmentRule(
            user_id=user.id, direction="income", label="Salary", amount=Decimal("3200"),
            cadence="monthly", next_date=date(2026, 7, 28),
            status=CommitmentStatus.CONFIRMED.value,
        )
        db_session.add(rule)
        db_session.commit()
        out = svc.skip_commitment(db_session, user, str(rule.id))
        assert out.next_date == date(2026, 8, 28)

    def test_skip_missing_returns_none(self, db_session):
        import uuid as _u
        user = _user(db_session)
        assert svc.skip_commitment(db_session, user, str(_u.uuid4())) is None


# --------------------------------------------------------------------------- #
# Merchant normalisation: the reason regular loan/bill payments went undetected
# --------------------------------------------------------------------------- #
from app.models import AccountRole, AccountType, CommitmentSource  # noqa: E402
from app.services.analytics.commitments import (  # noqa: E402
    _match_key,
    _normalise_merchant,
)
from app.services.analytics.common import default_role  # noqa: E402


def _tx_desc(db, account, amount, when, ttype="debit", description="X", merchant=None):
    """A transaction whose description and merchant_name differ — banks leave
    merchant_name null for direct debits, which is exactly the case that broke."""
    t = Transaction(
        account_id=account.id,
        # Both legs of a transfer share a description and date, so the account
        # and direction have to be part of the id to stay unique.
        external_id=f"tx-{account.id}-{ttype}-{description}-{when.isoformat()}",
        transaction_type=ttype, amount=Decimal(str(amount)), currency="GBP",
        description=description, merchant_name=merchant,
        transaction_date=datetime.combine(when, datetime.min.time(), tzinfo=timezone.utc),
    )
    db.add(t)
    db.commit()
    return t


class TestMerchantNormalisation:
    def test_strips_payment_reference(self):
        assert _normalise_merchant("LOAN PAYMENT REF 4471") == "LOAN PAYMENT REF"
        assert _normalise_merchant("LOAN PAYMENT REF 8123") == "LOAN PAYMENT REF"

    def test_strips_embedded_date(self):
        assert _normalise_merchant("DD TESCO BANK 12/07") == "DD TESCO BANK"
        assert _normalise_merchant("DD TESCO BANK 12-07-25") == "DD TESCO BANK"

    def test_keeps_short_digits_and_alphanumerics(self):
        # O2 and MONZO123 are merchant names, not references — stripping them
        # would over-merge unrelated payments.
        assert _normalise_merchant("O2") == "O2"
        assert _normalise_merchant("MONZO123") == "MONZO123"

    def test_falls_back_when_nothing_survives(self):
        assert _normalise_merchant("123456") == "123456"

    def test_case_and_punctuation_insensitive(self):
        assert _normalise_merchant("Netflix.com") == _normalise_merchant("NETFLIX COM")

    def test_match_key_unchanged_for_plain_merchants(self):
        """Existing stored keys must keep matching: for a merchant with no
        digits the new key is byte-identical to the old lower/strip form."""
        assert _match_key("expense", "Netflix") == "expense:netflix"
        assert _match_key("income", " Salary ") == "income:salary"


class TestDetectionExclusions:
    def test_loan_payment_with_varying_reference_is_detected(self, db_session):
        """The headline bug: a perfectly regular loan DD whose reference changes
        every month used to land in groups of one and never be suggested."""
        user = _user(db_session)
        acc = _account(db_session, user, name="Cur")
        base = svc._add_months(date.today(), -3)
        for i in range(4):
            _tx_desc(
                db_session, acc, 250, svc._add_months(base, i),
                description=f"LOAN PAYMENT REF {4471 + i}",
            )

        found = svc.detect_recurring(db_session, user)
        loans = [c for c in found if "LOAN PAYMENT" in c["label"].upper()]
        assert len(loans) == 1
        assert loans[0]["cadence"] == "monthly"
        assert loans[0]["amount"] == Decimal("250.00")

    def test_card_settlement_is_not_detected_as_commitment(self, db_session):
        """Repayments are already derived from the card's balance + schedule;
        detecting them again would double-count them in safe-to-spend."""
        user = _user(db_session)
        cur = _account(db_session, user, name="Cur")
        base = svc._add_months(date.today(), -3)
        for i in range(4):
            _tx_desc(
                db_session, cur, 300, svc._add_months(base, i),
                description="AMEX CARD PAYMENT",
            )

        labels = {c["label"].upper() for c in svc.detect_recurring(db_session, user)}
        assert "AMEX CARD PAYMENT" not in labels

    def test_incoming_transfer_leg_not_income_but_outgoing_leg_kept(self, db_session):
        """Moving money to your own savings isn't income — but the standing
        order leaving the current account is still a real monthly outflow."""
        user = _user(db_session)
        cur = _account(db_session, user, name="Cur")
        sav = _account(db_session, user, atype="SAVINGS", name="Sav")
        base = svc._add_months(date.today(), -3)
        for i in range(4):
            when = svc._add_months(base, i)
            _tx_desc(db_session, cur, 200, when, ttype="debit", description="MONTHLY SAVER")
            _tx_desc(db_session, sav, 200, when, ttype="credit", description="MONTHLY SAVER")

        found = svc.detect_recurring(db_session, user)
        directions = {(c["direction"], c["label"].upper()) for c in found}
        assert ("income", "MONTHLY SAVER") not in directions
        assert ("expense", "MONTHLY SAVER") in directions

    def test_excluded_account_generates_no_commitments(self, db_session):
        user = _user(db_session)
        other = _account(db_session, user, atype="OTHER", name="Other")
        base = svc._add_months(date.today(), -3)
        for i in range(4):
            _tx_desc(db_session, other, 75, svc._add_months(base, i), description="SOMETHING")

        assert svc.detect_recurring(db_session, user) == []


class TestLoanAccountRole:
    def test_loan_and_mortgage_count_as_liabilities(self, db_session):
        """They used to fall through to EXCLUDED, so a mortgage was invisible
        to net worth entirely."""
        user = _user(db_session)
        loan = _account(db_session, user, atype="LOAN", balance="-5000", name="Loan")
        mortgage = _account(db_session, user, atype="MORTGAGE", balance="-200000", name="Mortgage")
        assert default_role(loan) == AccountRole.CREDIT
        assert default_role(mortgage) == AccountRole.CREDIT

    def test_loan_alone_schedules_no_repayments(self, db_session):
        """Safety: without an explicit AccountSetting a loan must not put its
        whole balance into the forecast as a single payment."""
        user = _user(db_session)
        _account(db_session, user, atype="MORTGAGE", balance="-200000", name="Mortgage")
        events = svc.repayment_events(
            db_session, user, date.today(), date.today() + timedelta(days=90)
        )
        assert events == []


class TestMatchKeySelfHeal:
    def test_stale_detected_key_is_rekeyed(self, db_session):
        """match_key is DEK-encrypted so it can't be migrated in SQL — it heals
        on read, where the user's key is in scope."""
        user = _user(db_session)
        _account(db_session, user, name="Cur")
        rule = CommitmentRule(
            user_id=user.id, direction="expense", label="LOAN PAYMENT REF 4471",
            amount=Decimal("250"), cadence="monthly", next_date=date.today(),
            source=CommitmentSource.DETECTED.value,
            status=CommitmentStatus.CONFIRMED.value,
            match_key="expense:loan payment ref 4471",  # pre-normalisation key
        )
        db_session.add(rule)
        db_session.commit()

        svc.sync_suggestions(db_session, user)
        db_session.refresh(rule)
        assert rule.match_key == "expense:loan payment ref"

    def test_manual_key_is_left_alone(self, db_session):
        """A manual rule's key is the user's own merchant text, not ours to rewrite."""
        user = _user(db_session)
        _account(db_session, user, name="Cur")
        rule = CommitmentRule(
            user_id=user.id, direction="expense", label="My loan",
            amount=Decimal("250"), cadence="monthly", next_date=date.today(),
            source=CommitmentSource.MANUAL.value,
            status=CommitmentStatus.CONFIRMED.value,
            match_key="expense:santander 998877",
        )
        db_session.add(rule)
        db_session.commit()

        svc.sync_suggestions(db_session, user)
        db_session.refresh(rule)
        assert rule.match_key == "expense:santander 998877"
