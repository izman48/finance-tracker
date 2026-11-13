"""A commitment's category (T-24-2): the category of the most recent payment
that `classify_purchase` matches to it, or None when none matched.

There is no separate setup: a commitment sits in whatever category its
payments already have, like any other payment (owner, 2026-11-13). Budgets
use it to put a commitment's still-to-come instalments in a category.

Matching is the one predicate, `classify_purchase`, with that commitment's
own keys; there is no second comparison. One read of the user's own
transactions, bounded to `WINDOW_DAYS`, serves every commitment, so the
query count does not grow with the number of commitments. The category is
returned exactly as stored (bank text, rules, Claude's edits): callers
compare it by exact string only.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import Account, CommitmentRule, Transaction
from app.services.analytics.commitments import rule_match_keys, transaction_match_key
from app.services.analytics.common import _load, _today, resolve_roles
from app.services.analytics.spending import _effective_transfers, classify_purchase, financed_transaction_ids

WINDOW_DAYS = 400


def commitment_categories(db: Session, user, rules: Iterable[CommitmentRule]) -> dict[uuid.UUID, str | None]:
    """Each rule's id mapped to its most recent matched payment's category."""
    rules = list(rules)
    keys = {r.id: rule_match_keys(r) for r in rules}
    by_key: dict[str, list[CommitmentRule]] = defaultdict(list)
    for rule in rules:
        for key in keys[rule.id]:
            by_key[key].append(rule)
    latest: dict[uuid.UUID, Transaction] = {}
    if by_key:
        accounts, settings = _load(db, user)
        roles = resolve_roles(accounts, settings)
        txns = _recent_transactions(db, user)
        transfers = _effective_transfers(txns)
        financed = financed_transaction_ids(db, user)
        for tx in txns:
            # A shared key only narrows the candidates; classify_purchase,
            # given each candidate's own keys, decides the match.
            for rule in by_key.get(transaction_match_key(tx), ()):
                if classify_purchase(tx, transfers, roles, financed, keys[rule.id]) != "commitment":
                    continue
                best = latest.get(rule.id)
                if best is None or tx.transaction_date > best.transaction_date:
                    latest[rule.id] = tx
    return {r.id: latest[r.id].category if r.id in latest else None for r in rules}


def _recent_transactions(db: Session, user) -> list[Transaction]:
    since = datetime.combine(_today() - timedelta(days=WINDOW_DAYS), datetime.min.time(), timezone.utc)
    return (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == user.id, Transaction.transaction_date >= since)
        .all()
    )
