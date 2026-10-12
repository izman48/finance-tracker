"""Budget spend: the one counting rule for budgets (T-09-1; budgets concept
sections 2 and 15.3).

Budget tracking, History and the Cashflow projection all read spend from
`budget_spend`, so they can never disagree (three-sources rule). It is the
Spending screen's purchases lens with commitments excluded: card purchases
and cash purchases, by category, inside one cycle. Excluded, and reported
with their amounts so the budget screen reconciles to the transactions:

- `commitments`: spending matching a confirmed commitment (already inside
  safe-to-spend);
- `transfers`: money moved between the user's own accounts;
- `card_payoffs`: paying a card off (its purchases counted when made).

Income and refunds are never netted (fail safe: refunds never turn spending
into less spending). Transactions are the caller's own, read at request time
with their key and bounded to the window; nothing is cached or shared.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, AccountRole, Transaction
from app.services.analytics.commitments import commitment_match_keys, transaction_match_key
from app.services.analytics.common import _d, _load, resolve_roles
from app.services.analytics.spending import _effective_transfers, _is_card_repayment, financed_transaction_ids

UNCATEGORISED = "Uncategorized"
COUNTED_ROLES = (AccountRole.SPENDING, AccountRole.CREDIT)


@dataclass(frozen=True)
class BudgetSpend:
    by_category: dict[str, Decimal]
    excluded: dict[str, Decimal] = field(default_factory=dict)


def budget_spend(db: Session, user, start: date, end: date) -> BudgetSpend:
    """Purchases by category in [start, end], and what was left out."""
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
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
    transfers = _effective_transfers(txns)
    financed = financed_transaction_ids(db, user)
    commitment_keys = commitment_match_keys(db, user)

    by_category: dict[str, Decimal] = defaultdict(Decimal)
    excluded = {"commitments": Decimal(0), "transfers": Decimal(0), "card_payoffs": Decimal(0)}
    for tx in txns:
        if tx.transaction_type != "debit" or roles.get(tx.account_id) not in COUNTED_ROLES:
            continue  # income, refunds, savings and excluded accounts never count
        if tx.id in financed:
            continue  # on a payment plan: counted through its instalments
        amount = _d(tx.amount)
        # A card payoff is also an internal transfer (its two legs pair up),
        # so it's checked first to be named as what it is.
        if _is_card_repayment(tx, roles):
            excluded["card_payoffs"] += amount
        elif tx.id in transfers:
            excluded["transfers"] += amount
        elif transaction_match_key(tx) in commitment_keys:
            excluded["commitments"] += amount
        else:
            by_category[tx.category or UNCATEGORISED] += amount
    return BudgetSpend(by_category=dict(by_category), excluded=excluded)
