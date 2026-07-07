"""Spending ("where did it go"): breakdowns, drill-down, and the monthly trend.

Real spending = card purchases (debits on credit accounts) + cash purchases
(debits on spending accounts), excluding internal transfers and card
repayments (which just settle existing spending).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, AccountRole, PlannedItem, Transaction

from .commitments import commitment_match_keys, last_payday, transaction_match_key
from .common import _add_months, _d, _load, _today, resolve_roles

# Descriptions that indicate a transfer to settle a credit card (not new spend).
_CARD_PAYMENT_INDICATORS = (
    "american express", "amex", "monzo flex", "barclaycard",
    "credit card", "cc payment", "card payment",
)


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


def classify_noise(txns: list[Transaction], roles: dict) -> dict:
    """Map transaction id -> excluded reason for list display.

    Marks both halves of internal transfers, payments received onto credit
    cards, and card-settling debits from other accounts — the same signals the
    spending aggregates exclude, so the list and the totals can never disagree.
    """
    transfers = _detect_internal_transfers(txns)
    reasons: dict = {}
    for tx in txns:
        if tx.id in transfers:
            reasons[tx.id] = "internal_transfer"
            continue
        role = roles.get(tx.account_id)
        if role == AccountRole.CREDIT and tx.transaction_type == "credit":
            reasons[tx.id] = "card_payment"  # money arriving to settle the card
            continue
        if role != AccountRole.CREDIT and tx.transaction_type == "debit":
            desc = f"{tx.description or ''} {tx.merchant_name or ''}".lower()
            if any(ind in desc for ind in _CARD_PAYMENT_INDICATORS):
                reasons[tx.id] = "card_payment"  # the paying side
    return reasons


def financed_transaction_ids(db: Session, user) -> set:
    """Transaction ids that have been converted to an active payment plan.

    These are excluded from spending: the purchase is now paid in installments
    (which show in the forecast), so counting the original lump would double it.
    """
    rows = (
        db.query(PlannedItem.source_transaction_id)
        .filter(
            PlannedItem.user_id == user.id,
            PlannedItem.active.is_(True),
            PlannedItem.source_transaction_id.isnot(None),
        )
        .all()
    )
    return {r[0] for r in rows}


def get_spending(
    db: Session, user, period: str = "since_payday",
    frm: date | None = None, to: date | None = None,
    exclude_commitments: bool = False, lens: str = "money_out",
    hide_transfers: bool = False, hide_card_payments: bool = False,
) -> dict:
    """Spending breakdown for a period, under one of two lenses.

    - 'money_out' (default): cash that actually left the user's spending
      accounts — reconciles to a bank statement, and includes card repayments
      (the Amex payoff). Nothing is netted by default; transfers, card
      repayments and commitments are opt-in hides, and a `composition`
      names what's inside.
    - 'purchases': spend booked at purchase time (card purchases + cash
      purchases), excluding transfers and card repayments so a purchase is
      never double-counted with its later repayment.
    """
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    today = _today()
    start, end = _spending_range(db, user, period, frm, to, today)
    commitment_keys = commitment_match_keys(db, user)
    financed = financed_transaction_ids(db, user)

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

    by_category: dict[str, dict] = defaultdict(lambda: {"total": Decimal(0), "count": 0})
    by_merchant: dict[str, Decimal] = defaultdict(Decimal)

    if lens == "purchases":
        keys = commitment_keys if exclude_commitments else set()
        charged_to_credit = Decimal(0)
        paid_from_cash = Decimal(0)
        for tx, kind in _iter_spending(txns, transfers, roles, financed, keys):
            amount = _d(tx.amount)
            if kind == "credit":
                charged_to_credit += amount
            else:
                paid_from_cash += amount
            _tally(by_category, by_merchant, tx, amount)
        total = charged_to_credit + paid_from_cash
        composition = None
    else:  # money_out
        charged_to_credit = Decimal(0)
        paid_from_cash = Decimal(0)
        comp = {"card_repayments": Decimal(0), "transfers": Decimal(0), "commitments": Decimal(0), "other": Decimal(0)}
        total = Decimal(0)
        for tx in txns:
            for amount in [_money_out_amount(tx, roles, transfers, exclude_commitments, hide_transfers, hide_card_payments, commitment_keys)]:
                if amount is None:
                    continue
                total += amount
                # Composition (before hides remove them — but hidden ones
                # already returned None above, so this reflects what's counted).
                if tx.id in transfers:
                    comp["transfers"] += amount
                elif _is_card_repayment(tx, roles):
                    comp["card_repayments"] += amount
                elif transaction_match_key(tx) in commitment_keys:
                    comp["commitments"] += amount
                else:
                    comp["other"] += amount
                _tally(by_category, by_merchant, tx, amount)
        composition = comp

    categories = sorted(
        ({"category": k, "total": v["total"], "count": v["count"]} for k, v in by_category.items()),
        key=lambda c: c["total"], reverse=True,
    )
    merchants = sorted(
        ({"merchant": k, "total": v} for k, v in by_merchant.items()),
        key=lambda m: m["total"], reverse=True,
    )

    return {
        "lens": lens,
        "period": period,
        "period_start": start,
        "period_end": end,
        "total_spent": total,
        "charged_to_credit": charged_to_credit,
        "paid_from_cash": paid_from_cash,
        "composition": composition,
        "by_category": categories,
        "top_merchants": merchants,
    }


def _tally(by_category, by_merchant, tx, amount):
    category = tx.category or "Uncategorized"
    by_category[category]["total"] += amount
    by_category[category]["count"] += 1
    by_merchant[tx.merchant_name or tx.description or "Unknown"] += amount


def _is_card_repayment(tx, roles) -> bool:
    """A debit on a spending account that settles a credit card."""
    if roles.get(tx.account_id) != AccountRole.SPENDING or tx.transaction_type != "debit":
        return False
    desc = f"{tx.description or ''} {tx.merchant_name or ''}".lower()
    return any(ind in desc for ind in _CARD_PAYMENT_INDICATORS)


def _money_out_amount(tx, roles, transfers, exclude_commitments, hide_transfers, hide_card_payments, commitment_keys):
    """The signed amount this transaction contributes to 'money out of my bank',
    or None if it doesn't count (not a spending-account debit, or opted out).

    Money out = every debit that left a spending (current) account. Card
    purchases sit on the card account and are deferred, so they're not cash out
    of the bank; card *repayments* (a debit on the current account) are.
    """
    if roles.get(tx.account_id) != AccountRole.SPENDING or tx.transaction_type != "debit":
        return None
    if hide_transfers and tx.id in transfers:
        return None
    if hide_card_payments and _is_card_repayment(tx, roles):
        return None
    if exclude_commitments and transaction_match_key(tx) in commitment_keys:
        return None
    return _d(tx.amount)


def _iter_spending(txns, transfers, roles, financed, commitment_keys):
    """Yield (tx, kind) for each transaction that counts as real spending.

    kind is "credit" (a card purchase) or "cash" (paid from a spending account).
    Shared by the breakdown and the drill-down so the two can never disagree:
    same exclusions (internal transfers, card repayments, financed purchases,
    and — when requested — confirmed commitments).
    """
    for tx in txns:
        if tx.id in transfers or tx.transaction_type != "debit":
            continue
        if tx.id in financed:
            continue  # moved to a payment plan — counted via its installments
        if commitment_keys and transaction_match_key(tx) in commitment_keys:
            continue
        role = roles.get(tx.account_id)
        if role == AccountRole.CREDIT:
            yield tx, "credit"
        elif role == AccountRole.SPENDING:
            desc = f"{tx.description or ''} {tx.merchant_name or ''}".lower()
            if any(ind in desc for ind in _CARD_PAYMENT_INDICATORS):
                continue  # repayment, not new spending
            yield tx, "cash"
        # savings / excluded accounts: not spending


def spending_transactions(
    db: Session, user, period: str = "since_payday",
    frm: date | None = None, to: date | None = None,
    exclude_commitments: bool = False,
    category: str | None = None, merchant: str | None = None, kind: str | None = None,
) -> list[dict]:
    """The individual transactions behind a spending figure (a category, a
    merchant, or the cash/credit split) — for drilling into "what makes this up"."""
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    acc_names = {a.id: a.display_name for a in accounts}
    today = _today()
    start, end = _spending_range(db, user, period, frm, to, today)
    commitment_keys = commitment_match_keys(db, user) if exclude_commitments else set()
    financed = financed_transaction_ids(db, user)

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

    out: list[dict] = []
    for tx, k in _iter_spending(txns, transfers, roles, financed, commitment_keys):
        if kind and k != kind:
            continue
        cat = tx.category or "Uncategorized"
        if category is not None and cat != category:
            continue
        mer = tx.merchant_name or tx.description or "Unknown"
        if merchant is not None and mer != merchant:
            continue
        out.append({
            "id": str(tx.id),
            "date": tx.transaction_date.date(),
            "description": tx.description,
            "merchant": tx.merchant_name,
            "amount": _d(tx.amount),
            "category": cat,
            "account": acc_names.get(tx.account_id, ""),
            "kind": k,
        })
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


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
    financed = financed_transaction_ids(db, user)
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
        if tx.id in financed:
            continue  # moved to a payment plan — counted via its installments
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
