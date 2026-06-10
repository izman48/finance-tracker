"""Categorization rule engine.

Rules (exact / contains / regex, optionally grouped into packs) map transaction
text to categories. Manual per-transaction categories are "locked" and never
overwritten. When several rules match, precedence is deliberately boring:

  1. the user's own rules (learned/manual) beat imported pack rules
  2. exact beats contains beats regex
  3. longer patterns beat shorter ones
"""
import logging
import re

from sqlalchemy.orm import Session, joinedload

from app.models import Account, CategoryRule, Transaction, merchant_match_key

logger = logging.getLogger(__name__)

# Regexes are user-supplied (and importable from other users); cap complexity.
MAX_PATTERN_LENGTH = 200
_MATCH_TYPE_RANK = {"exact": 0, "contains": 1, "regex": 2}


def validate_pattern(pattern: str, match_type: str) -> str | None:
    """Return an error message if the pattern is unusable, else None."""
    if not pattern or not pattern.strip():
        return "Pattern is empty"
    if len(pattern) > MAX_PATTERN_LENGTH:
        return f"Pattern longer than {MAX_PATTERN_LENGTH} characters"
    if match_type == "regex":
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return f"Invalid regex: {exc}"
    return None


def _fields_for(tx: Transaction, match_field: str) -> list[str]:
    merchant = (tx.merchant_name or "").strip()
    description = (tx.description or "").strip()
    if match_field == "merchant":
        return [merchant]
    if match_field == "description":
        return [description]
    return [merchant, description]


def _rule_matches(rule: CategoryRule, tx: Transaction) -> bool:
    pattern = rule.pattern.strip()
    fields = [f for f in _fields_for(tx, rule.match_field) if f]
    if not fields:
        return False

    if rule.match_type == "exact":
        return any(f.lower() == pattern.lower() for f in fields)
    if rule.match_type == "contains":
        return any(pattern.lower() in f.lower() for f in fields)
    if rule.match_type == "regex":
        try:
            compiled = re.compile(pattern[:MAX_PATTERN_LENGTH], re.IGNORECASE)
        except re.error:
            return False
        return any(compiled.search(f) for f in fields)
    return False


def _precedence(rule: CategoryRule) -> tuple:
    """Sort key: lower sorts first = wins."""
    own = 0 if rule.source in ("learned", "manual") else 1
    return (own, _MATCH_TYPE_RANK.get(rule.match_type, 3), -len(rule.pattern))


def active_rules(db: Session, user_id) -> list[CategoryRule]:
    """The user's enabled rules (whose packs are also enabled), best-first."""
    rules = (
        db.query(CategoryRule)
        .options(joinedload(CategoryRule.pack))
        .filter(CategoryRule.user_id == user_id, CategoryRule.enabled.is_(True))
        .all()
    )
    rules = [r for r in rules if r.pack is None or r.pack.enabled]
    rules.sort(key=_precedence)
    return rules


def categorize(rules: list[CategoryRule], tx: Transaction) -> str | None:
    """Best-matching category for a transaction, or None. `rules` must be
    pre-sorted by active_rules()."""
    for rule in rules:
        if _rule_matches(rule, tx):
            return rule.category
    return None


def apply_rules(db: Session, user_id, transactions: list[Transaction]) -> int:
    """Apply the user's rules to the given transactions (skipping locked ones).

    Used for newly synced transactions and retroactive runs. Does not commit —
    the caller owns the session. Returns the number of transactions changed.
    """
    rules = active_rules(db, user_id)
    if not rules:
        return 0

    changed = 0
    for tx in transactions:
        if tx.category_locked:
            continue
        category = categorize(rules, tx)
        if category and category != tx.category:
            tx.category = category
            changed += 1
    if changed:
        logger.info(f"Rules categorized {changed} transactions for user {user_id}")
    return changed


def apply_rules_to_all(db: Session, user_id) -> int:
    """Retroactively run the rule engine over every unlocked transaction."""
    transactions = (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == user_id, Transaction.category_locked.is_(False))
        .all()
    )
    return apply_rules(db, user_id, transactions)


def learn_and_apply(db: Session, user_id, transaction: Transaction) -> int:
    """Remember the category the user just set and spread it to the same merchant.

    Called after a user categorizes `transaction` by hand: the transaction
    itself is locked, an exact rule for its merchant is upserted (cleared
    category = rule deleted), and the rule is applied to the merchant's other
    unlocked transactions. Does not commit — the caller owns the session.
    """
    transaction.category_locked = bool(transaction.category)

    key = merchant_match_key(transaction.merchant_name, transaction.description)
    if not key:
        return 0

    rule = (
        db.query(CategoryRule)
        .filter(
            CategoryRule.user_id == user_id,
            CategoryRule.pattern == key,
            CategoryRule.match_type == "exact",
            CategoryRule.source == "learned",
        )
        .first()
    )

    if not transaction.category:
        if rule:
            db.delete(rule)
        return 0

    if rule:
        rule.category = transaction.category
        rule.enabled = True
    else:
        rule = CategoryRule(
            user_id=user_id,
            pattern=key,
            match_type="exact",
            match_field="any",
            category=transaction.category,
            source="learned",
        )
        db.add(rule)

    # Spread to the merchant's other unlocked transactions.
    updated = 0
    for tx in _same_merchant(db, user_id, key):
        if tx.id != transaction.id and not tx.category_locked and tx.category != transaction.category:
            tx.category = transaction.category
            updated += 1
    if updated:
        logger.info(f"Auto-categorized {updated} transactions as {transaction.category!r}")
    return updated


def _same_merchant(db: Session, user_id, key: str) -> list[Transaction]:
    """All of the user's transactions whose merchant key equals `key`.

    SQL mirror of merchant_match_key: merchant_name unless null/empty, else
    description; trimmed and lowercased.
    """
    from sqlalchemy import func

    sql_key = func.lower(
        func.trim(func.coalesce(func.nullif(Transaction.merchant_name, ""), Transaction.description))
    )
    return (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == user_id, sql_key == key)
        .all()
    )
