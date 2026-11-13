"""A commitment's category (T-24-2): the category of the most recent payment
that `classify_purchase` matches to it, or None when none matched.

There is no separate setup: a commitment sits in whatever category its
payments already have, like any other payment (owner, 2026-11-13). Budgets
use it to put a commitment's still-to-come instalments in a category.

Matching is the one predicate, `classify_purchase`, with the one matcher
(`commitment_matcher`: key and amount); there is no second comparison. One read of the user's own
transactions, bounded to `WINDOW_DAYS`, serves every commitment, so the
query count does not grow with the number of commitments. The category is
returned exactly as stored (bank text, rules, Claude's edits): callers
compare it by exact string only.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.orm import Session

from app.models import Account, CommitmentRule, Transaction
from app.services.analytics.commitments import commitment_matcher
from app.services.analytics.common import _load, _today, resolve_roles
from app.services.analytics.spending import _effective_transfers, classify_purchase, financed_transaction_ids
from app.services.claude_keep import before_claude, claude_rows

WINDOW_DAYS = 400


def commitment_categories(db: Session, user, rules: Iterable[CommitmentRule]) -> dict[uuid.UUID, str | None]:
    """Each rule's id mapped to its most recent matched payment's category."""
    rules = list(rules)
    latest: dict[uuid.UUID, Transaction] = {}
    if rules:
        matcher = commitment_matcher(db, user, rules + _before_claude_amounts(db, user, rules))
        accounts, settings = _load(db, user)
        roles = resolve_roles(accounts, settings)
        txns = _recent_transactions(db, user)
        transfers = _effective_transfers(txns)
        financed = financed_transaction_ids(db, user)
        for tx in txns:
            if classify_purchase(tx, transfers, roles, financed, matcher) != "commitment":
                continue
            rule = matcher.rule_for(tx)
            best = latest.get(rule.id)
            if best is None or tx.transaction_date > best.transaction_date:
                latest[rule.id] = tx
    return {r.id: latest[r.id].category if r.id in latest else None for r in rules}


def _before_claude_amounts(db: Session, user, rules: list[CommitmentRule]) -> list[SimpleNamespace]:
    """Each rule again at its amount before Claude's pending change, if any:
    an unkept change to the amount must not move a commitment out of its
    category (and so its instalments out of a budget's coming up)."""
    claude = claude_rows(db, user.id, [r.id for r in rules])
    out = []
    for rule in rules:
        if rule.id in claude:
            amount = before_claude(rule, claude[rule.id]).amount
            if amount != rule.amount:
                out.append(SimpleNamespace(id=rule.id, direction=rule.direction, label=rule.label,
                                           match_key=rule.match_key, amount=amount))
    return out


def _recent_transactions(db: Session, user) -> list[Transaction]:
    since = datetime.combine(_today() - timedelta(days=WINDOW_DAYS), datetime.min.time(), timezone.utc)
    return (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == user.id, Transaction.transaction_date >= since)
        .all()
    )
