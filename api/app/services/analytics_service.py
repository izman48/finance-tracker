"""Cashflow analytics: account roles, recurring detection, and the summary figures.

This is the engine behind safe-to-spend. Phase 1 covers role resolution, recurring
income/expense detection (ported & generalised from the frontend Bills logic),
credit-card repayment scheduling, and the dashboard summary. The occurrence and
repayment helpers are written to be reused by the Phase 2 projection.
"""
from __future__ import annotations

import calendar
import statistics
import uuid as _uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import (
    Account,
    AccountRole,
    AccountSetting,
    AccountType,
    Asset,
    CommitmentCadence,
    CommitmentDirection,
    CommitmentRule,
    CommitmentSource,
    CommitmentStatus,
    PlannedItem,
    RepaymentScheduleItem,
    RepaymentStrategy,
    Transaction,
)

# Detection thresholds (mirrors the frontend Bills heuristic).
_MIN_OCCURRENCES = 3
_MAX_INTERVAL_CV = 0.30  # std-dev must be < 30% of the mean interval

_DEFAULT_ROLE_BY_TYPE = {
    AccountType.TRANSACTION: AccountRole.SPENDING,
    AccountType.SAVINGS: AccountRole.SAVINGS,
    AccountType.CREDIT_CARD: AccountRole.CREDIT,
}


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _d(value) -> Decimal:
    return Decimal(str(value or 0))


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
def default_role(account: Account) -> AccountRole:
    """Role to assume when the user hasn't configured the account yet."""
    try:
        atype = AccountType(account.account_type)
    except ValueError:
        return AccountRole.EXCLUDED
    return _DEFAULT_ROLE_BY_TYPE.get(atype, AccountRole.EXCLUDED)


def resolve_roles(
    accounts: list[Account], settings: dict,
) -> dict:
    """Map account_id -> AccountRole, using settings then type defaults."""
    roles: dict = {}
    for acc in accounts:
        setting = settings.get(acc.id)
        roles[acc.id] = AccountRole(setting.role) if setting else default_role(acc)
    return roles


# --------------------------------------------------------------------------- #
# Date / cadence helpers
# --------------------------------------------------------------------------- #
def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _cadence_from_interval(avg_days: float) -> tuple[str, int | None, int | None]:
    """Map an average gap in days to (cadence, interval_days, interval_months)."""
    if avg_days <= 10:
        return CommitmentCadence.WEEKLY.value, None, None
    if 25 <= avg_days <= 35:
        return CommitmentCadence.MONTHLY.value, None, None
    if 80 <= avg_days <= 100:
        return CommitmentCadence.EVERY_N_MONTHS.value, None, 3
    if 170 <= avg_days <= 195:
        return CommitmentCadence.EVERY_N_MONTHS.value, None, 6
    return CommitmentCadence.CUSTOM_DAYS.value, max(1, round(avg_days)), None


def _step(d: date, cadence: str, interval_days: int | None, interval_months: int | None) -> date:
    if cadence == CommitmentCadence.WEEKLY.value:
        return d + timedelta(days=7)
    if cadence == CommitmentCadence.MONTHLY.value:
        return _add_months(d, 1)
    if cadence == CommitmentCadence.EVERY_N_MONTHS.value:
        return _add_months(d, interval_months or 1)
    return d + timedelta(days=interval_days or 30)


def commitment_occurrences(rule: CommitmentRule, start: date, end: date) -> list[date]:
    """Dates on which a commitment falls within [start, end] (inclusive)."""
    out: list[date] = []
    d = rule.next_date
    # Roll forward to the window if next_date is in the past.
    guard = 0
    while d < start and guard < 600:
        d = _step(d, rule.cadence, rule.interval_days, rule.interval_months)
        guard += 1
    while d <= end and guard < 600:
        out.append(d)
        d = _step(d, rule.cadence, rule.interval_days, rule.interval_months)
        guard += 1
    return out


# --------------------------------------------------------------------------- #
# Credit-card repayment scheduling
# --------------------------------------------------------------------------- #
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
        n = setting.repayment_interval_months or 3
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


# --------------------------------------------------------------------------- #
# Planned items (payment plans / one-off / recurring)
# --------------------------------------------------------------------------- #
def installment_amount(total, installments: int, apr=None, fee=None) -> Decimal:
    """Per-installment payment. Even split by default; simple interest + fee if set."""
    n = installments or 1
    base = _d(total)
    if fee:
        base += _d(fee)
    if apr:
        # Simple interest over the plan term (installments assumed ~monthly).
        base += _d(total) * (_d(apr) / Decimal(100)) * (Decimal(n) / Decimal(12))
    return (base / Decimal(n)).quantize(Decimal("0.01"))


def planned_events(item: PlannedItem, start: date, end: date) -> list[tuple]:
    """(date, signed_amount) movements for a planned item within [start, end]."""
    sign = Decimal(1) if item.direction == CommitmentDirection.INCOME.value else Decimal(-1)
    out: list[tuple] = []

    if item.kind == "one_off":
        if start <= item.start_date <= end:
            out.append((item.start_date, sign * _d(item.amount)))
        return out

    if item.kind == "installment_plan":
        per = installment_amount(item.total_amount, item.installments or 1, item.apr, item.fee_amount)
        d = item.start_date
        for _ in range(item.installments or 0):
            if start <= d <= end:
                out.append((d, sign * per))
            d = _step(d, item.cadence or "monthly", item.interval_days, item.interval_months)
        return out

    # recurring
    d = item.start_date
    guard = 0
    while d <= end and guard < 600:
        if d >= start and (item.end_date is None or d <= item.end_date):
            out.append((d, sign * _d(item.amount)))
        d = _step(d, item.cadence or "monthly", item.interval_days, item.interval_months)
        guard += 1
    return out


# --------------------------------------------------------------------------- #
# Recurring detection (ported & generalised from BillsPage)
# --------------------------------------------------------------------------- #
def _match_key(direction: str, merchant: str) -> str:
    return f"{direction}:{merchant.strip().lower()}"


def merchant_match_key(direction: str, merchant: str | None) -> str | None:
    """Public: match key for a user-supplied merchant/description, or None if blank.

    Lets a manually-added commitment be tied to the real transactions it should
    exclude, using the same keying as auto-detection.
    """
    if not merchant or not merchant.strip():
        return None
    return _match_key(direction, merchant)


def transaction_match_key(tx: Transaction) -> str:
    """The key a transaction would group under in recurring detection."""
    direction = (
        CommitmentDirection.INCOME.value
        if tx.transaction_type == "credit"
        else CommitmentDirection.EXPENSE.value
    )
    return _match_key(direction, (tx.merchant_name or tx.description or "Unknown").strip())


def commitment_match_keys(db: Session, user) -> set[str]:
    """Match keys of confirmed commitments, for flagging/excluding their transactions.

    Detected commitments carry the match_key they were grouped under; manual ones
    fall back to their label, which catches commitments added from a transaction.
    """
    rules = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    keys: set[str] = set()
    for r in rules:
        if r.match_key:
            keys.add(r.match_key)
        keys.add(_match_key(r.direction, r.label))
    return keys


def detect_recurring(db: Session, user) -> list[dict]:
    """Detect recurring income (credits) and expenses (debits) from history."""
    txns = (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == user.id)
        .all()
    )

    groups: dict[tuple[str, str], list[Transaction]] = defaultdict(list)
    for tx in txns:
        direction = (
            CommitmentDirection.INCOME.value
            if tx.transaction_type == "credit"
            else CommitmentDirection.EXPENSE.value
        )
        merchant = (tx.merchant_name or tx.description or "Unknown").strip()
        groups[(direction, merchant)].append(tx)

    candidates: list[dict] = []
    for (direction, merchant), group in groups.items():
        if len(group) < _MIN_OCCURRENCES:
            continue
        group.sort(key=lambda t: t.transaction_date)
        intervals = [
            (group[i].transaction_date - group[i - 1].transaction_date).days
            for i in range(1, len(group))
        ]
        intervals = [iv for iv in intervals if iv > 0]
        if len(intervals) < 2:
            continue
        mean = statistics.mean(intervals)
        if mean <= 0:
            continue
        stdev = statistics.pstdev(intervals)
        if stdev > mean * _MAX_INTERVAL_CV:
            continue  # not consistent enough to be "recurring"

        avg_amount = sum((_d(t.amount) for t in group), Decimal(0)) / len(group)
        last_date = group[-1].transaction_date.date()
        cadence, interval_days, interval_months = _cadence_from_interval(mean)

        # If the next expected occurrence is well overdue, the pattern has
        # probably stopped (cancelled sub, ended salary) — don't suggest it.
        today = _today()
        if (today - last_date).days > mean * 2 + 7:
            continue

        # Otherwise surface the first occurrence that is still ahead of us.
        next_date = _step(last_date, cadence, interval_days, interval_months)
        guard = 0
        while next_date < today and guard < 600:
            next_date = _step(next_date, cadence, interval_days, interval_months)
            guard += 1

        candidates.append(
            {
                "direction": direction,
                "label": merchant,
                "amount": avg_amount.quantize(Decimal("0.01")),
                "cadence": cadence,
                "interval_days": interval_days,
                "interval_months": interval_months,
                "next_date": next_date,
                "match_key": _match_key(direction, merchant),
            }
        )
    return candidates


def commitment_from_transaction(db: Session, user, transaction_id: str, cadence: str = "monthly"):
    """Create (or confirm) a recurring commitment derived from a transaction.

    Uses the same match_key as auto-detection so it dedupes with any suggestion
    for the same merchant rather than creating a duplicate.
    """
    try:
        tid = transaction_id if isinstance(transaction_id, _uuid.UUID) else _uuid.UUID(str(transaction_id))
    except (ValueError, AttributeError):
        return None
    tx = (
        db.query(Transaction)
        .join(Account)
        .filter(Transaction.id == tid, Account.user_id == user.id)
        .first()
    )
    if not tx:
        return None

    direction = (
        CommitmentDirection.INCOME.value
        if tx.transaction_type == "credit"
        else CommitmentDirection.EXPENSE.value
    )
    label = (tx.merchant_name or tx.description or "Recurring").strip()
    # "yearly" is an alias clients may send — stored as every-12-months.
    if cadence == "yearly":
        cadence = CommitmentCadence.EVERY_N_MONTHS.value
        interval_months = 12
    else:
        interval_months = 3 if cadence == CommitmentCadence.EVERY_N_MONTHS.value else None

    # Next occurrence: step from the transaction date forward until it's in the future.
    d = tx.transaction_date.date()
    today = _today()
    guard = 0
    while d <= today and guard < 600:
        d = _step(d, cadence, None, interval_months)
        guard += 1

    key = _match_key(direction, label)
    rule = (
        db.query(CommitmentRule)
        .filter(CommitmentRule.user_id == user.id, CommitmentRule.match_key == key)
        .first()
    )
    if rule:
        rule.status = CommitmentStatus.CONFIRMED.value
        rule.amount = _d(tx.amount)
        rule.cadence = cadence
        rule.interval_months = interval_months
        rule.next_date = d
    else:
        rule = CommitmentRule(
            user_id=user.id,
            direction=direction,
            label=label,
            amount=_d(tx.amount),
            cadence=cadence,
            interval_months=interval_months,
            next_date=d,
            source=CommitmentSource.MANUAL.value,
            status=CommitmentStatus.CONFIRMED.value,
            match_key=key,
        )
        db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def sync_suggestions(db: Session, user) -> None:
    """Persist newly-detected commitments as `suggested`, without touching ones
    the user has already confirmed or dismissed."""
    existing_rules = db.query(CommitmentRule).filter(CommitmentRule.user_id == user.id).all()
    existing_keys = {rule.match_key for rule in existing_rules if rule.match_key}

    # Maintenance: advance stale next_dates so the review list never shows a
    # "next" occurrence in the past. (Forecasting already rolls forward the
    # same way in commitment_occurrences; this just persists it for display.)
    today = _today()
    for rule in existing_rules:
        guard = 0
        while rule.next_date and rule.next_date < today and guard < 600:
            rule.next_date = _step(rule.next_date, rule.cadence, rule.interval_days, rule.interval_months)
            guard += 1

    for cand in detect_recurring(db, user):
        if cand["match_key"] in existing_keys:
            continue
        db.add(
            CommitmentRule(
                user_id=user.id,
                direction=cand["direction"],
                label=cand["label"],
                amount=cand["amount"],
                cadence=cand["cadence"],
                interval_days=cand["interval_days"],
                interval_months=cand["interval_months"],
                next_date=cand["next_date"],
                source=CommitmentSource.DETECTED.value,
                status=CommitmentStatus.SUGGESTED.value,
                match_key=cand["match_key"],
            )
        )
    db.commit()


# --------------------------------------------------------------------------- #
# Summary
# --------------------------------------------------------------------------- #
def _load(db: Session, user):
    accounts = db.query(Account).filter(Account.user_id == user.id).all()
    settings = {
        s.account_id: s
        for s in db.query(AccountSetting).filter(AccountSetting.user_id == user.id).all()
    }
    return accounts, settings


def next_payday(db: Session, user, from_date: date) -> date | None:
    """Next confirmed income date on/after from_date."""
    incomes = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.direction == CommitmentDirection.INCOME.value,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    dates = [occ for r in incomes for occ in commitment_occurrences(r, from_date, from_date + timedelta(days=400))]
    return min(dates) if dates else None


def _step_repayment(setting: AccountSetting, d: date) -> date | None:
    """Next repayment date strictly after d, per the card's cadence."""
    return next_repayment_date(setting, d + timedelta(days=1))


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
        n = max(1, s.repayment_installments or 1)
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

        # Scheduled strategy: emit exactly what the user listed, ignoring cadence.
        if s.repayment_strategy == RepaymentStrategy.SCHEDULED.value:
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
        balance = abs(_d(acc.current_balance))
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


def assets_total(db: Session, user, as_of: date | None = None) -> Decimal:
    """Sum of each manual asset's most recent valuation on/before as_of."""
    assets = db.query(Asset).filter(Asset.user_id == user.id).all()
    total = Decimal(0)
    for asset in assets:
        current = None
        for v in asset.valuations:  # ordered by valued_at
            if as_of is None or v.valued_at <= as_of:
                current = v.value
        if current is not None:
            total += _d(current)
    return total


def net_worth_history(db: Session, user, months: int = 12) -> list[dict]:
    """Net worth at month-ends (plus today), looking back `months` months.

    Bank balances are reconstructed by walking transactions backwards from the
    current balance; manual assets contribute their latest valuation on/before
    each date.
    """
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    today = _today()

    points: list[date] = [today]
    cursor = date(today.year, today.month, 1) - timedelta(days=1)
    for _ in range(months):
        points.append(cursor)
        cursor = date(cursor.year, cursor.month, 1) - timedelta(days=1)
    points = sorted(set(points))
    earliest = datetime.combine(points[0], datetime.min.time(), tzinfo=timezone.utc)

    bank_at: dict[date, Decimal] = {p: Decimal(0) for p in points}
    for acc in accounts:
        role = roles[acc.id]
        if role == AccountRole.EXCLUDED:
            continue
        txs = (
            db.query(Transaction.transaction_date, Transaction.transaction_type, Transaction.amount)
            .filter(Transaction.account_id == acc.id, Transaction.transaction_date > earliest)
            .all()
        )
        for p in points:
            # Net signed flow after p: inflows positive, outflows negative.
            delta_after = sum(
                (
                    _d(amount) if getattr(ttype, "value", ttype) == "credit" else -_d(amount)
                    for tx_date, ttype, amount in txs
                    if tx_date.date() > p
                ),
                Decimal(0),
            )
            if role == AccountRole.CREDIT:
                # Owed grows with spending (debits): owed(p) = owed_now + delta_after.
                owed_at = abs(_d(acc.current_balance)) + delta_after
                bank_at[p] -= max(owed_at, Decimal(0))
            else:
                bank_at[p] += _d(acc.current_balance) - delta_after

    out = []
    for p in points:
        assets_at = assets_total(db, user, as_of=p)
        out.append(
            {
                "date": p.isoformat(),
                "bank": bank_at[p],
                "assets": assets_at,
                "net_worth": bank_at[p] + assets_at,
            }
        )
    return out


def get_summary(db: Session, user) -> dict:
    """The dashboard cashflow summary."""
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    today = _today()

    available_cash = Decimal(0)
    overdraft_cushion = Decimal(0)
    credit_owed = Decimal(0)
    savings_total = Decimal(0)
    for acc in accounts:
        role = roles[acc.id]
        if role == AccountRole.SPENDING:
            available_cash += _d(acc.current_balance)
            setting = settings.get(acc.id)
            if setting and setting.overdraft_limit:
                overdraft_cushion += _d(setting.overdraft_limit)
        elif role == AccountRole.SAVINGS:
            savings_total += _d(acc.current_balance)
        elif role == AccountRole.CREDIT:
            credit_owed += abs(_d(acc.current_balance))

    payday = next_payday(db, user, today)
    window_end = payday or (today + timedelta(days=30))

    # Confirmed expense commitments due before the next payday.
    expense_rules = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.direction == CommitmentDirection.EXPENSE.value,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    committed = Decimal(0)
    for rule in expense_rules:
        committed += _d(rule.amount) * len(commitment_occurrences(rule, today, window_end))
    repayments = repayment_events(db, user, today, window_end)
    committed += sum((r["amount"] for r in repayments), Decimal(0))

    safe_to_spend = max(Decimal(0), available_cash - committed)

    # Savable: surplus expected to survive a 30-day window (incl. next income).
    horizon = today + timedelta(days=30)
    income_rules = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.direction == CommitmentDirection.INCOME.value,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    income_30 = sum(
        (_d(r.amount) * len(commitment_occurrences(r, today, horizon)) for r in income_rules),
        Decimal(0),
    )
    expense_30 = sum(
        (_d(r.amount) * len(commitment_occurrences(r, today, horizon)) for r in expense_rules),
        Decimal(0),
    )
    repay_30 = sum((r["amount"] for r in repayment_events(db, user, today, horizon)), Decimal(0))
    savable = max(Decimal(0), available_cash + income_30 - expense_30 - repay_30)

    manual_assets = assets_total(db, user)

    return {
        "available_cash": available_cash,
        "overdraft_cushion": overdraft_cushion,
        "credit_owed": credit_owed,
        "savings_total": savings_total,
        "assets_total": manual_assets,
        "net_worth": available_cash + savings_total + manual_assets - credit_owed,
        "committed_before_payday": committed,
        "safe_to_spend": safe_to_spend,
        "savable": savable,
        "next_payday": payday,
        # Show upcoming card repayments over a display horizon, independent of the
        # payday window — so a bill due just after payday is still visible.
        "next_repayments": repayment_events(db, user, today, today + timedelta(days=92)),
        "accounts": [_account_summary(acc, roles[acc.id], settings.get(acc.id)) for acc in accounts],
    }


def _account_summary(acc: Account, role: AccountRole, s: AccountSetting | None) -> dict:
    return {
        "id": str(acc.id),
        "display_name": acc.display_name,
        "provider_name": acc.provider_name,
        "account_type": acc.account_type,
        "role": role.value,
        "current_balance": acc.current_balance,
        "overdraft_limit": s.overdraft_limit if s else None,
        "repayment_cadence": s.repayment_cadence if s else None,
        "repayment_day": s.repayment_day if s else None,
        "repayment_interval_months": s.repayment_interval_months if s else None,
        "repayment_anchor_date": s.repayment_anchor_date if s else None,
        "repayment_strategy": s.repayment_strategy if s else None,
        "repayment_fixed_amount": s.repayment_fixed_amount if s else None,
        "repayment_installments": s.repayment_installments if s else None,
        "pay_from_account_id": str(s.pay_from_account_id) if s and s.pay_from_account_id else None,
    }


# --------------------------------------------------------------------------- #
# Forecast (the projection / graph)
# --------------------------------------------------------------------------- #
def _horizon_end(db: Session, user, horizon: str, today: date) -> date:
    """Resolve a horizon keyword to an end date.

    Accepts `payday`, `month`, or any number of days (e.g. 30, 90, 180, 365),
    capped at 730 days.
    """
    if horizon == "payday":
        payday = next_payday(db, user, today + timedelta(days=1))
        return payday or (today + timedelta(days=30))
    if horizon == "month":
        return date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    if str(horizon).isdigit():
        return today + timedelta(days=min(int(horizon), 730))
    return today + timedelta(days=30)


def get_forecast(db: Session, user, horizon: str = "payday") -> dict:
    """Project the spending-account balance forward across the horizon.

    Applies confirmed recurring income/expenses and credit-card repayments as
    dated movements, producing a daily running-balance timeline plus the lowest
    point and any breach of the £0 / overdraft lines.
    """
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    today = _today()
    end = _horizon_end(db, user, horizon, today)

    start_balance = sum(
        (_d(a.current_balance) for a in accounts if roles[a.id] == AccountRole.SPENDING),
        Decimal(0),
    )
    overdraft_limit = sum(
        (_d(settings[a.id].overdraft_limit) for a in accounts
         if roles[a.id] == AccountRole.SPENDING and a.id in settings and settings[a.id].overdraft_limit),
        Decimal(0),
    )

    # Collect signed, dated events within (today, end].
    events_by_day: dict[date, list[dict]] = defaultdict(list)
    confirmed = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    for rule in confirmed:
        sign = Decimal(1) if rule.direction == CommitmentDirection.INCOME.value else Decimal(-1)
        for occ in commitment_occurrences(rule, today + timedelta(days=1), end):
            events_by_day[occ].append(
                {
                    "label": rule.label,
                    "amount": sign * _d(rule.amount),
                    "kind": rule.direction,
                }
            )
    for r in repayment_events(db, user, today + timedelta(days=1), end):
        events_by_day[r["due_date"]].append(
            {"label": r["label"], "amount": -_d(r["amount"]), "kind": "repayment"}
        )
    planned = (
        db.query(PlannedItem)
        .filter(PlannedItem.user_id == user.id, PlannedItem.active.is_(True))
        .all()
    )
    for item in planned:
        for occ_date, amount in planned_events(item, today + timedelta(days=1), end):
            events_by_day[occ_date].append(
                {"label": item.name, "amount": amount, "kind": "planned"}
            )

    # Walk day by day, accumulating the running balance.
    timeline: list[dict] = [{"date": today, "balance": start_balance, "events": []}]
    balance = start_balance
    min_balance, min_date = start_balance, today
    day = today
    while day < end:
        day += timedelta(days=1)
        day_events = events_by_day.get(day, [])
        for ev in day_events:
            balance += ev["amount"]
        timeline.append({"date": day, "balance": balance, "events": day_events})
        if balance < min_balance:
            min_balance, min_date = balance, day

    breaches = []
    if min_balance < 0:
        breaches.append("zero")
    if overdraft_limit > 0 and min_balance < -overdraft_limit:
        breaches.append("overdraft")

    return {
        "horizon": horizon,
        "horizon_end": end,
        "start_balance": start_balance,
        "end_balance": balance,
        "min_balance": min_balance,
        "min_date": min_date,
        "overdraft_limit": overdraft_limit,
        "breaches": breaches,
        "timeline": timeline,
    }


# --------------------------------------------------------------------------- #
# Spending ("where did it go")
# --------------------------------------------------------------------------- #
# Descriptions that indicate a transfer to settle a credit card (not new spend).
_CARD_PAYMENT_INDICATORS = (
    "american express", "amex", "monzo flex", "barclaycard",
    "credit card", "cc payment", "card payment",
)


def _step_back(d: date, cadence: str, interval_days: int | None, interval_months: int | None) -> date:
    if cadence == CommitmentCadence.WEEKLY.value:
        return d - timedelta(days=7)
    if cadence == CommitmentCadence.MONTHLY.value:
        return _add_months(d, -1)
    if cadence == CommitmentCadence.EVERY_N_MONTHS.value:
        return _add_months(d, -(interval_months or 1))
    return d - timedelta(days=interval_days or 30)


def last_payday(db: Session, user, today: date) -> date | None:
    """Most recent confirmed income date on/before today (steps back from next_date)."""
    incomes = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.direction == CommitmentDirection.INCOME.value,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    best: date | None = None
    for r in incomes:
        d = r.next_date
        guard = 0
        while d > today and guard < 600:
            d = _step_back(d, r.cadence, r.interval_days, r.interval_months)
            guard += 1
        if d <= today and (best is None or d > best):
            best = d
    return best


def _spending_range(db, user, period: str, frm: date | None, to: date | None, today: date):
    if period == "custom" and frm and to:
        return frm, to
    if period == "this_month":
        return date(today.year, today.month, 1), today
    if period == "last_30":
        return today - timedelta(days=30), today
    # since_payday (default)
    payday = last_payday(db, user, today)
    return (payday or today - timedelta(days=30)), today


def _detect_internal_transfers(txns: list[Transaction]) -> set:
    """IDs of debit/credit pairs that look like money moving between own accounts."""
    excluded: set = set()
    ordered = sorted(txns, key=lambda t: t.transaction_date)
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if (b.transaction_date - a.transaction_date).days > 2:
                break
            if a.account_id == b.account_id:
                continue
            if abs(_d(a.amount) - _d(b.amount)) > Decimal("0.01"):
                continue
            if {a.transaction_type, b.transaction_type} == {"debit", "credit"}:
                excluded.add(a.id)
                excluded.add(b.id)
    return excluded


def get_spending(
    db: Session, user, period: str = "since_payday",
    frm: date | None = None, to: date | None = None,
    exclude_commitments: bool = False,
) -> dict:
    """Spending breakdown for a period, aware of credit vs cash.

    Real spending = card purchases (debits on credit accounts) + cash purchases
    (debits on spending accounts), excluding internal transfers and card
    repayments (which just settle existing spending). With exclude_commitments,
    confirmed recurring bills are dropped too, leaving only discretionary spend.
    """
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    today = _today()
    start, end = _spending_range(db, user, period, frm, to, today)
    commitment_keys = commitment_match_keys(db, user) if exclude_commitments else set()

    txns = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user.id,
            Transaction.transaction_date >= datetime.combine(start, datetime.min.time(), timezone.utc),
            Transaction.transaction_date <= datetime.combine(end, datetime.max.time(), timezone.utc),
        )
        .all()
    )
    transfers = _detect_internal_transfers(txns)

    charged_to_credit = Decimal(0)
    paid_from_cash = Decimal(0)
    by_category: dict[str, dict] = defaultdict(lambda: {"total": Decimal(0), "count": 0})
    by_merchant: dict[str, Decimal] = defaultdict(Decimal)

    for tx in txns:
        if tx.id in transfers or tx.transaction_type != "debit":
            continue
        if commitment_keys and transaction_match_key(tx) in commitment_keys:
            continue
        role = roles.get(tx.account_id)
        amount = _d(tx.amount)
        if role == AccountRole.CREDIT:
            charged_to_credit += amount
        elif role == AccountRole.SPENDING:
            desc = f"{tx.description or ''} {tx.merchant_name or ''}".lower()
            if any(ind in desc for ind in _CARD_PAYMENT_INDICATORS):
                continue  # repayment, not new spending
            paid_from_cash += amount
        else:
            continue  # savings / excluded

        category = tx.category or "Uncategorized"
        by_category[category]["total"] += amount
        by_category[category]["count"] += 1
        merchant = tx.merchant_name or tx.description or "Unknown"
        by_merchant[merchant] += amount

    total = charged_to_credit + paid_from_cash
    categories = sorted(
        ({"category": k, "total": v["total"], "count": v["count"]} for k, v in by_category.items()),
        key=lambda c: c["total"], reverse=True,
    )
    merchants = sorted(
        ({"merchant": k, "total": v} for k, v in by_merchant.items()),
        key=lambda m: m["total"], reverse=True,
    )[:10]

    return {
        "period": period,
        "period_start": start,
        "period_end": end,
        "total_spent": total,
        "charged_to_credit": charged_to_credit,
        "paid_from_cash": paid_from_cash,
        "by_category": categories,
        "top_merchants": merchants,
    }


def _month_key(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def get_spending_trend(
    db: Session, user, months: int = 6, exclude_commitments: bool = False
) -> dict:
    """Real spending per calendar month over the last `months` months.

    Same noise-filtering as get_spending: internal transfers and card repayments
    are excluded so a bad month reflects actual spending, not money shuffling.
    """
    months = max(1, min(months, 24))
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    commitment_keys = commitment_match_keys(db, user) if exclude_commitments else set()
    today = _today()
    first_of_this_month = date(today.year, today.month, 1)
    start_month = _add_months(first_of_this_month, -(months - 1))

    txns = (
        db.query(Transaction)
        .join(Account)
        .filter(
            Account.user_id == user.id,
            Transaction.transaction_date >= datetime.combine(start_month, datetime.min.time(), timezone.utc),
            Transaction.transaction_date <= datetime.combine(today, datetime.max.time(), timezone.utc),
        )
        .all()
    )
    transfers = _detect_internal_transfers(txns)

    # Seed every month in range so quiet months show as zero, not gaps.
    buckets: dict[str, dict] = {}
    m = start_month
    while m <= first_of_this_month:
        buckets[_month_key(m)] = {"total": Decimal(0), "credit": Decimal(0), "cash": Decimal(0)}
        m = _add_months(m, 1)

    for tx in txns:
        if tx.id in transfers or tx.transaction_type != "debit":
            continue
        if commitment_keys and transaction_match_key(tx) in commitment_keys:
            continue
        role = roles.get(tx.account_id)
        amount = _d(tx.amount)
        if role == AccountRole.CREDIT:
            kind = "credit"
        elif role == AccountRole.SPENDING:
            desc = f"{tx.description or ''} {tx.merchant_name or ''}".lower()
            if any(ind in desc for ind in _CARD_PAYMENT_INDICATORS):
                continue
            kind = "cash"
        else:
            continue
        b = buckets.setdefault(_month_key(tx.transaction_date.date()), {"total": Decimal(0), "credit": Decimal(0), "cash": Decimal(0)})
        b["total"] += amount
        b[kind] += amount

    rows = [
        {
            "month": key,
            "total": v["total"],
            "charged_to_credit": v["credit"],
            "paid_from_cash": v["cash"],
        }
        for key, v in sorted(buckets.items())
    ]
    return {"months": rows}
