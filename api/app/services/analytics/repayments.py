"""Credit-card repayment scheduling: when payments fall and how the balance spreads."""
from __future__ import annotations

import calendar
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    CardPlan,
    AccountRole,
    AccountSetting,
    CommitmentDirection,
    RepaymentCadence,
    RepaymentScheduleItem,
    RepaymentStrategy,
)
from app.schemas import MAX_REPAYMENT_INTERVAL_MONTHS

from app.services.balance_sign import credit_owed
from app.services import card_plans

from .cadence import commitment_occurrences
from app.services.linked_commitments import linked_commitment_ids

from .card_links import credit_card_ids, link_card_commitments
from .common import _add_months, _d, _load, _today, resolve_roles
from .statements import current_positions


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
        return _next_day_of_month(setting.repayment_day or 1, from_date)
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


def _next_day_of_month(day: int, from_date: date) -> date:
    """First date on/after from_date falling on this day of the month
    (clamped to the month's last day)."""
    candidate = from_date.replace(day=min(day, calendar.monthrange(from_date.year, from_date.month)[1]))
    if candidate < from_date:
        nxt = _add_months(from_date, 1)
        candidate = nxt.replace(day=min(day, calendar.monthrange(nxt.year, nxt.month)[1]))
    return candidate


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
    positions = None  # loaded on first use
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

        if not _pays_on_card_due_date(s) and not s.repayment_cadence:
            continue
        if positions is None:
            positions = current_positions(db, user, accounts)
        position = positions.get(acc.id)
        pay_days = _pay_days(s, position, start)
        if s.repayment_strategy == RepaymentStrategy.STATEMENT_BALANCE.value:
            plan = _statement_plan(s, credit_owed(acc), position, pay_days)
        else:
            # Walk the schedule over the pay days (at most 200 of them).
            plan = list(zip(pay_days, _repayment_schedule(s, credit_owed(acc))[:201]))
        for due, amount in plan:
            if start <= due <= end and amount > 0:
                out.append({"account_id": str(acc.id), "label": acc.display_name, "amount": amount, "due_date": due})
    out.sort(key=lambda r: r["due_date"])
    return out


_CADENCES = frozenset(c.value for c in RepaymentCadence)


def _pays_on_card_due_date(s: AccountSetting) -> bool:
    """Pay day "card due date": chosen, or implied by `statement_balance`
    with no pay day set (its default) or one we don't know (cadence is free
    text until it is validated on write): never a missing payment."""
    if s.repayment_cadence == RepaymentCadence.CARD_DUE_DATE.value:
        return True
    return (
        s.repayment_strategy == RepaymentStrategy.STATEMENT_BALANCE.value
        and s.repayment_cadence not in _CADENCES
    )


def _pay_days(s: AccountSetting, position, start: date) -> Iterator[date]:
    """The card's repayment dates from `start` on.

    "Card due date": the current statement's due date, then the same day each
    month, rolled forward past dates before `start`. With no statement, the
    card's configured day of the month, or 30 days from today: a missing date
    never means a missing payment. Otherwise the configured cadence.
    """
    if not _pays_on_card_due_date(s):
        if s.repayment_cadence not in _CADENCES:
            # Legacy free text (cadence wasn't validated before T-10-4a): pay
            # at each month-end rather than never (lead, fail-safe).
            yield from _month_ends(start)
            return
        due = next_repayment_date(s, start)
        while due is not None:
            yield due
            due = _step_repayment(s, due)
        return
    if position is not None:
        anchor = position.statement.due_date
    elif s.repayment_day:
        anchor = _next_day_of_month(s.repayment_day, start)
    else:
        anchor = _today() + timedelta(days=30)
    months = 0
    while _add_months(anchor, months) < start:
        months += 1
    while True:
        yield _add_months(anchor, months)
        months += 1


def _month_ends(start: date) -> Iterator[date]:
    month = start.replace(day=1)
    while True:
        end = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
        if end >= start:
            yield end
        month = _add_months(month, 1)


def _statement_plan(s: AccountSetting, owed: Decimal, position, pay_days: Iterator[date]) -> list[tuple]:
    """(date, amount) payments under `statement_balance`.

    The amount still due goes on the statement's pay day and the unbilled
    spend on the one after, so the total is never below the full balance.
    With no statement, or once its due date has passed with no newer one,
    the full current balance goes on the next pay day (fail-safe).
    """
    if owed <= 0:
        return []
    if position is None or position.statement.due_date < _today():
        return [(_next_pay_day(pay_days), owed)]
    plan = []
    # On a cadence, a paid statement's own payment day has already gone.
    if _pays_on_card_due_date(s) or not position.paid:
        statement_day = _next_pay_day(pay_days)
        if not position.paid:
            plan.append((statement_day, position.amount_still_due))
    if position.unbilled > 0:
        plan.append((_next_pay_day(pay_days), position.unbilled))
    return plan


def _next_pay_day(pay_days: Iterator[date]) -> date:
    """The next pay day; if the days run out, 30 days from today (a missing
    date must never mean a missing payment, or an error)."""
    return next(pay_days, None) or _today() + timedelta(days=30)


# Far enough to reach the end of any schedule (120 installments, or the
# 200-step guard on weekly/fixed), so the last due date is the real last one.
_SCHEDULE_REACH = timedelta(days=366 * 20)


def _card_ties(db: Session, user, rules: list, start: date):
    """Which commitments are a credit card's repayment, by the one rule the
    summary, forecast and projections share: the stored card link (T-08-8).

    Unlinked commitments are linked first where that is certain (see
    card_links). A commitment is tied to a card only when it is an expense
    whose `card_account_id` is one of the user's credit cards AND that card
    has a repayment schedule from `start`. A link to anything else (not a
    credit card, no repayment config, a deleted card) is not a tie, so both
    are counted: overstating outgoings is the safe side.

    Returns (schedule, last_due, ties): the card repayment events from
    `start`, each card's last due date, and {rule id: card id}.
    """
    link_card_commitments(db, user)
    schedule = repayment_events(db, user, start, start + _SCHEDULE_REACH)
    last_due: dict[str, date] = {}
    for r in schedule:
        last_due[r["account_id"]] = max(r["due_date"], last_due.get(r["account_id"], r["due_date"]))
    cards = credit_card_ids(db, user)
    # Never a liability's repayment, whatever link is stored (sec on #183).
    loan_bills = linked_commitment_ids(db, user.id)

    ties: dict = {}
    for rule in rules:
        card = rule.card_account_id
        if (
            rule.direction == CommitmentDirection.EXPENSE.value
            and rule.id not in loan_bills
            and card in cards
            and str(card) in last_due
        ):
            ties[rule.id] = str(card)
    return schedule, last_due, ties


def cards_with_linked_bills(db: Session, user, rules: list, start: date) -> set[str]:
    """Ids of the credit cards that have a commitment tied to them (see
    _card_ties). For those, which of the repayment and the bill is counted
    depends on the window, so a single "next payment" can't be promised."""
    _schedule, _last_due, ties = _card_ties(db, user, rules, start)
    return set(ties.values())


def card_repayment_rule_ids(db: Session, user, rules: list, start: date) -> set:
    """Ids of the commitments that are a credit card's repayment (see _card_ties)."""
    _schedule, _last_due, ties = _card_ties(db, user, rules, start)
    return set(ties)


def scheduled_outflows(db: Session, user, rules: list, start: date, end: date):
    """Confirmed-commitment occurrences and card repayment events in
    [start, end], with each card's repayment counted once.

    Returns (occurrences, repayments): occurrences as (rule, date) pairs,
    repayments as repayment_events dicts.

    A confirmed expense commitment whose label is a repayment descriptor for
    exactly one of the user's credit cards ("AMEX", "MONZO FLEX"), when that
    card has a repayment schedule, is the same money as that card's repayment
    events, up to the schedule's last due date. For each such card the larger of the two in the window is kept: the
    events pay off today's balance, the commitment may reflect a bill already
    building, and under-stating what goes out is the unsafe direction. Any
    commitment less clearly tied to one card is always counted.
    """
    schedule, last_due, ties = _card_ties(db, user, rules, start)
    repayments = [r for r in schedule if r["due_date"] <= end]

    occurrences: list[tuple] = []
    overlap: dict[str, list[tuple]] = {}  # card id -> covered (rule, date)
    for rule in rules:
        card_id = ties.get(rule.id)
        for d in commitment_occurrences(rule, start, end):
            if card_id and d <= last_due[card_id]:
                overlap.setdefault(card_id, []).append((rule, d))
            else:
                occurrences.append((rule, d))

    for card_id, covered in overlap.items():
        committed = sum((_d(rule.amount) for rule, _ in covered), Decimal(0))
        repaying = sum((r["amount"] for r in repayments if r["account_id"] == card_id), Decimal(0))
        if committed > repaying:
            occurrences.extend(covered)
            repayments = [r for r in repayments if r["account_id"] != card_id]
    occurrences.sort(key=lambda o: o[1])
    # Card plan instalments always count, after the per-card choice above, so
    # a commitment tied to the card never drops them (sec T-12-5; the safe side).
    repayments = sorted(repayments + plan_instalment_events(db, user, start, end), key=lambda r: r["due_date"])
    return occurrences, repayments


def plan_instalment_events(db: Session, user, start: date, end: date) -> list[dict]:
    """Card plan instalments + fees due in [start, end] (T-12-5b, owner D3).

    Each future instalment joins the card's next pay day on or after its
    date; with no pay day (no repayment set up, or the card has gone) it
    leaves on the instalment date itself. Counted whatever the provider's
    verification status (sec T-12-5 b). Past instalments are already on the
    card (statement or unbilled), so they are never added again."""
    plans = db.query(CardPlan).filter(CardPlan.user_id == user.id).all()
    if not plans:
        return []
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    by_id = {a.id: a for a in accounts}
    positions = current_positions(db, user, accounts)
    today = _today()
    out = []
    for plan in plans:
        card = by_id.get(plan.card_account_id)
        s = settings.get(card.id) if card is not None and roles[card.id] == AccountRole.CREDIT else None
        has_pay_day = s is not None and s.repayment_strategy != RepaymentStrategy.SCHEDULED.value and (
            _pays_on_card_due_date(s) or bool(s.repayment_cadence))
        amount = card_plans.monthly_total(plan)
        for n in range(plan.instalments_remaining):
            charged = _add_months(plan.next_date, n)
            if charged < today:
                continue
            due = next(_pay_days(s, positions.get(card.id), charged), charged) if has_pay_day else charged
            if start <= due <= end:
                out.append({"account_id": str(card.id) if card is not None else None,
                            "label": f"{plan.name} instalment", "amount": amount, "due_date": due,
                            "card_plan": True})
    return out
