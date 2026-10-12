"""Budget spend: the one counting rule for budgets (T-09-1; budgets concept
sections 2 and 15.3).

Budget tracking, History and the Cashflow projection all read spend from
`budget_spend`, so they can never disagree (three-sources rule). It is the
Spending screen's purchases lens with commitments excluded (the same
`classify_purchase` predicate): card purchases
and cash purchases, by category, inside one cycle. Excluded, and reported
with their amounts so the budget screen reconciles to the transactions:

- `commitments`: spending matching a confirmed commitment (already inside
  safe-to-spend);
- `transfers`: money moved between the user's own accounts;
- `card_payoffs`: paying a card off (its purchases counted when made);
- `financed`: a purchase moved to a payment plan (counted through its
  instalments, which are planned items).

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

from app.models import Account, Transaction
from app.services.analytics.commitments import commitment_match_keys
from app.services.analytics.common import _d, _load, resolve_roles
from app.services.analytics.spending import _effective_transfers, classify_purchase, financed_transaction_ids

UNCATEGORISED = "Uncategorized"
# classify_purchase's reasons, as reported in `excluded`.
EXCLUDED = {"commitment": "commitments", "transfer": "transfers", "card_payoff": "card_payoffs",
            "financed": "financed"}


@dataclass(frozen=True)
class BudgetSpend:
    by_category: dict[str, Decimal]
    excluded: dict[str, Decimal] = field(default_factory=dict)
    # Commitment-matched spending by category: a category that is mostly
    # commitments can't have a budget (T-09-2).
    commitments_by_category: dict[str, Decimal] = field(default_factory=dict)


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
    excluded = {name: Decimal(0) for name in EXCLUDED.values()}
    commitments: dict[str, Decimal] = defaultdict(Decimal)
    for tx in txns:
        kind = classify_purchase(tx, transfers, roles, financed, commitment_keys)
        if kind in ("credit", "cash"):
            by_category[tx.category or UNCATEGORISED] += _d(tx.amount)
        elif kind is not None:
            excluded[EXCLUDED[kind]] += _d(tx.amount)
            if kind == "commitment":
                commitments[tx.category or UNCATEGORISED] += _d(tx.amount)
    return BudgetSpend(by_category=dict(by_category), excluded=excluded, commitments_by_category=dict(commitments))
