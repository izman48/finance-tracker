"""Budget spend: the one counting rule for budgets (T-09-1; budgets concept
sections 2 and 15.3).

Budget tracking, History and the Cashflow projection all read spend from
`budget_spend`, so they can never disagree (three-sources rule). It is the
Spending screen's purchases lens with commitments excluded (the same
`classify_purchase` predicate): card purchases
and cash purchases, by category, inside one cycle. A payment matching a
confirmed commitment counts too when its own category is in `budgeted`
(exact text; T-24-3, owner 2026-11-13: a commitment counts inside its
budget category, when paid). Excluded, and reported with their amounts so
the budget screen reconciles to the transactions:

- `commitments`: spending matching a confirmed commitment whose category
  has no budget (already inside safe-to-spend);
- `commitments_no_category`: the same, for payments with no category;
- `transfers`: money moved between the user's own accounts;
- `card_payoffs`: paying a card off (its purchases counted when made);
- `financed`: a purchase moved to a payment plan (counted through its
  instalments, which are planned items).

Income and refunds are never netted on their own: refunds never turn
spending into less spending. The one exception is a paid-back mark, which
the user (through Claude) made explicitly, which is logged and which can be
undone (T-03-4): `services/paid_back.py` nets them, a spend mark in the
spend's own window and a category mark in its credit's, floored at £0.
`gross_by_category` is the spend before marks, for which categories may
have a budget (T-03-2 T5). Transactions and marks are the caller's own,
read at request time with their key and bounded to the window; nothing is
cached or shared.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, RepaymentMark, Transaction
from app.services.analytics.commitments import commitment_match_keys
from app.services.analytics.common import _d, _load, resolve_roles
from app.services.analytics.spending import _effective_transfers, classify_purchase, financed_transaction_ids
from app.services.paid_back import UNCATEGORISED, PaidBack, net_paid_back
from app.services.repayment_marks import active_marks

# classify_purchase's reasons, as reported in `excluded`.
EXCLUDED = {"commitment": "commitments", "transfer": "transfers", "card_payoff": "card_payoffs",
            "financed": "financed"}


@dataclass(frozen=True)
class BudgetSpend:
    # Net of paid-back marks.
    by_category: dict[str, Decimal]
    excluded: dict[str, Decimal] = field(default_factory=dict)
    # Commitment-matched spending left out, by category: suggestions skip a
    # category that is mostly commitments (T-09-2).
    commitments_by_category: dict[str, Decimal] = field(default_factory=dict)
    # Commitment payments counted above, and what classified them, so pace
    # can match each to its commitment with the same predicate (T-24-5).
    counted_commitments: list[Transaction] = field(default_factory=list)
    match_context: tuple = (frozenset(), {}, frozenset())
    # Before marks: which categories may have a budget (T-03-2 T5).
    gross_by_category: dict[str, Decimal] = field(default_factory=dict)
    # "Paid back by others": every mark netted here, excess included.
    paid_back: Decimal = Decimal(0)
    paid_back_marks: list[PaidBack] = field(default_factory=list)
    # Category marks beyond what the category spent here: shown, never income.
    paid_back_excess: dict[str, Decimal] = field(default_factory=dict)


def budget_spend(db: Session, user, start: date, end: date,
                 extra_marks: Sequence[RepaymentMark] = (),
                 budgeted: Collection[str] = frozenset()) -> BudgetSpend:
    """Purchases by category in [start, end], net of paid-back marks, and
    what was left out. `extra_marks`: unsaved marks a preview proposes
    (T-03-2 T7), netted as if saved. `budgeted`: the categories whose
    commitment payments count (those with an active, unpaused budget)."""
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
    excluded = {name: Decimal(0) for name in (*EXCLUDED.values(), "commitments_no_category")}
    commitments: dict[str, Decimal] = defaultdict(Decimal)
    counted_commitments: list[Transaction] = []
    counted: dict[uuid.UUID, Transaction] = {}
    for tx in txns:
        kind = classify_purchase(tx, transfers, roles, financed, commitment_keys)
        if kind in ("credit", "cash") or (kind == "commitment" and tx.category in budgeted):
            by_category[tx.category or UNCATEGORISED] += _d(tx.amount)
            counted[tx.id] = tx
            if kind == "commitment":
                counted_commitments.append(tx)
        elif kind == "commitment" and not tx.category:
            excluded["commitments_no_category"] += _d(tx.amount)
        elif kind is not None:
            excluded[EXCLUDED[kind]] += _d(tx.amount)
            if kind == "commitment":  # categorised: the branch above took the rest
                commitments[tx.category] += _d(tx.amount)
    gross = dict(by_category)
    marks = active_marks(db, user.id, extra=extra_marks)
    paid_back, excess = net_paid_back(by_category, marks, counted, start, end)
    return BudgetSpend(
        by_category=dict(by_category), excluded=excluded, commitments_by_category=dict(commitments),
        counted_commitments=counted_commitments, match_context=(transfers, roles, financed),
        gross_by_category=gross, paid_back=sum((p.amount for p in paid_back), Decimal(0)),
        paid_back_marks=paid_back, paid_back_excess=excess,
    )

