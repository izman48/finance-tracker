"""Credit-card repayment scheduling: when payments fall and how the balance spreads."""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    AccountRole,
    AccountSetting,
    CommitmentDirection,
    RepaymentScheduleItem,
    RepaymentStrategy,
)
from app.schemas import MAX_REPAYMENT_INTERVAL_MONTHS

from app.services.balance_sign import credit_owed, names_card

from .cadence import commitment_occurrences
from .common import _add_months, _d, _load, resolve_roles


DEFAULT_INTERVAL_MONTHS = 3


def _interval_months(setting: AccountSetting) -> int:
    """Months between every-N-months repayments. A stored value outside the
    API's 1..MAX_REPAYMENT_INTERVAL_MONTHS (only reachable by bypassing it)
    falls back to the default, so a schedule never steps backwards and drops
    payments out of the forecast."""
    n = setting.repayment_interval_months
    if n is None or not 1 <= n <= MAX_REPAYMENT_INTERVAL_MONTHS:
        return DEFAULT_INTERVAL_MONTHS
    return n


def next_repayment_date(setting: AccountSetting, from_date: date) -> date | None:
    """First repayment date on/after from_date for a configured credit account."""
    cadence = setting.repayment_cadence
    if not cadence:
        return None
    if cadence == "end_of_month":
        last = date(from_date.year, from_date.month, calendar.monthrange(from_date.year, from_date.month)[1])
        if last >= from_date:
            return last
        nxt = _add_months(from_date, 1)
        return date(nxt.year, nxt.month, calendar.monthrange(nxt.year, nxt.month)[1])
    if cadence == "monthly":
        day = setting.repayment_day or 1
        candidate = from_date.replace(day=min(day, calendar.monthrange(from_date.year, from_date.month)[1]))
        if candidate < from_date:
            nxt = _add_months(from_date, 1)
            candidate = nxt.replace(day=min(day, calendar.monthrange(nxt.year, nxt.month)[1]))
        return candidate
    if cadence == "weekly":
        anchor = setting.repayment_anchor_date or from_date
        d = anchor
        while d < from_date:
            d += timedelta(days=7)
        return d
    if cadence == "every_n_months":
        n = _interval_months(setting)
        d = setting.repayment_anchor_date or from_date
        guard = 0
        while d < from_date and guard < 200:
            d = _add_months(d, n)
            guard += 1
        return d
    return None


def repayment_amount(setting: AccountSetting, balance: Decimal) -> Decimal:
    strategy = setting.repayment_strategy or RepaymentStrategy.FULL_BALANCE.value
    if strategy == RepaymentStrategy.FIXED.value:
        return _d(setting.repayment_fixed_amount)
    if strategy == RepaymentStrategy.MINIMUM_PERCENT.value:
        pct = _d(setting.repayment_fixed_amount) / Decimal(100)
        return (balance * pct).quantize(Decimal("0.01"))
    return balance  # full_balance


def _step_repayment(setting: AccountSetting, d: date) -> date | None:
    """Next repayment date strictly after d, per the card's cadence.

    Weekly and every-N-months cadences count from their anchor date. With no
    anchor (the "First payment" date is optional in settings) they count from
    d itself; asking next_repayment_date would treat d + 1 day as the anchor
    and put every payment on consecutive days.
    """
    if not setting.repayment_anchor_date:
        if setting.repayment_cadence == "weekly":
            return d + timedelta(days=7)
        if setting.repayment_cadence == "every_n_months":
            return _add_months(d, _interval_months(setting))
    return next_repayment_date(setting, d + timedelta(days=1))


MAX_INSTALLMENTS = 120  # same bound the settings API enforces


def _installment_count(setting: AccountSetting) -> int:
    """N for the installments strategy. A count outside 1..MAX_INSTALLMENTS
    (only reachable by bypassing the API) means one payment, not a split."""
    n = setting.repayment_installments
    if n is None or not 1 <= n <= MAX_INSTALLMENTS:
        return 1
    return n


def _repayment_schedule(s: AccountSetting, balance: Decimal) -> list[Decimal]:
    """Payment amounts that pay the *current* balance down to zero.

    The total always equals the balance — we never assume the balance recurs
    (future card spending is unknown). Strategies differ only in how the known
    balance is spread:
      - full_balance: one payment of the whole balance (e.g. Amex).
      - installments: balance / N over N payments (e.g. Monzo Flex).
      - fixed: the fixed amount each cycle until cleared (last = remainder).
    """
    strategy = s.repayment_strategy or RepaymentStrategy.FULL_BALANCE.value
    if balance <= 0:
        return []

    if strategy == RepaymentStrategy.INSTALLMENTS.value:
        n = _installment_count(s)
        per = (balance / Decimal(n)).quantize(Decimal("0.01"))
    elif strategy == RepaymentStrategy.FIXED.value:
        amt = _d(s.repayment_fixed_amount)
        if amt <= 0:
            return [balance]
        import math
        n = max(1, math.ceil(balance / amt))
        per = amt
    else:  # full_balance — one payment of the whole balance
        n = 1
        per = balance

    amounts: list[Decimal] = []
    paid = Decimal(0)
    for i in range(n):
        amount = (balance - paid) if i == n - 1 else per  # last clears any remainder
        amounts.append(amount)
        paid += amount
    return amounts


def _scheduled_repayments(db: Session, user) -> dict:
    """User-listed scheduled repayments grouped by account_id (for `scheduled` cards)."""
    items = (
        db.query(RepaymentScheduleItem)
        .filter(RepaymentScheduleItem.user_id == user.id)
        .all()
    )
    by_account: dict = {}
    for item in items:
        by_account.setdefault(item.account_id, []).append(item)
    return by_account


def repayment_events(db: Session, user, start: date, end: date) -> list[dict]:
    """Credit-card repayments due in [start, end] that pay the balance down to zero."""
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    scheduled = _scheduled_repayments(db, user)
    out: list[dict] = []
    for acc in accounts:
        if roles[acc.id] != AccountRole.CREDIT:
            continue
        s = settings.get(acc.id)
        if not s:
            continue

        # Scheduled strategy: emit exactly what the user listed, ignoring
        # cadence, but nothing for a card that owes nothing or is in credit.
        if s.repayment_strategy == RepaymentStrategy.SCHEDULED.value:
            if credit_owed(acc) <= 0:
                continue
            for item in scheduled.get(acc.id, []):
                amt = _d(item.amount)
                if start <= item.due_date <= end and amt > 0:
                    out.append({
                        "account_id": str(acc.id), "label": acc.display_name,
                        "amount": amt, "due_date": item.due_date,
                    })
            continue

        if not s.repayment_cadence:
            continue
        balance = credit_owed(acc)
        amounts = _repayment_schedule(s, balance)
        if not amounts:
            continue

        # Walk the schedule from the first due date; emit those within [start, end].
        due = next_repayment_date(s, start)
        guard = 0
        for amount in amounts:
            if due is None or guard > 200:
                break
            if start <= due <= end and amount > 0:
                out.append({"account_id": str(acc.id), "label": acc.display_name, "amount": amount, "due_date": due})
            due = _step_repayment(s, due)
            guard += 1
    out.sort(key=lambda r: r["due_date"])
    return out


# Far enough to reach the end of any schedule (120 installments, or the
# 200-step guard on weekly/fixed), so the last due date is the real last one.
_SCHEDULE_REACH = timedelta(days=366 * 20)


def card_repayment_cover(db: Session, user, rules: list, today: date) -> dict:
    """rule id -> last repayment date of the card that confirmed expense
    commitment pays.

    A commitment named for a card ("AMEX", "MONZO FLEX") whose card has a
    repayment set up is the same money as that card's repayment events, up to
    the schedule's last date. Only a commitment that names exactly one such
    card is covered; anything less certain is left out, so it is still counted
    (over-stating what goes out is safe, hiding it is not).
    """
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    last_due: dict[str, date] = {}
    for r in repayment_events(db, user, today, today + _SCHEDULE_REACH):
        last_due[r["account_id"]] = max(r["due_date"], last_due.get(r["account_id"], r["due_date"]))
    cards = [a for a in accounts if roles[a.id] == AccountRole.CREDIT and str(a.id) in last_due]

    cover: dict = {}
    for rule in rules:
        if rule.direction != CommitmentDirection.EXPENSE.value:
            continue
        named = [a for a in cards if names_card(rule.label, a)]
        if len(named) == 1:
            cover[rule.id] = last_due[str(named[0].id)]
    return cover


def uncovered_occurrences(rule, start: date, end: date, cover: dict) -> list[date]:
    """The rule's occurrences in [start, end] that a card's repayment events
    do not already count (see card_repayment_cover)."""
    until = cover.get(rule.id)
    occurrences = commitment_occurrences(rule, start, end)
    return occurrences if until is None else [d for d in occurrences if d > until]
