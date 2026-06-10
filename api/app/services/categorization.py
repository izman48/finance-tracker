"""Auto-categorization: learn merchant→category rules from user edits and
apply them to existing and newly synced transactions."""
import logging

from sqlalchemy.orm import Session

from app.models import Account, CategoryRule, Transaction, merchant_match_key

logger = logging.getLogger(__name__)


def learn_and_apply(db: Session, user_id, transaction: Transaction) -> int:
    """Remember the category the user just set and spread it to the same merchant.

    Called after a user categorizes `transaction`. Upserts the rule and applies
    it to all of the user's other transactions with the same merchant key.
    Clearing a category deletes the rule. Returns how many other transactions
    were updated. Does not commit — the caller owns the session.
    """
    key = merchant_match_key(transaction.merchant_name, transaction.description)
    if not key:
        return 0

    rule = (
        db.query(CategoryRule)
        .filter(CategoryRule.user_id == user_id, CategoryRule.match_key == key)
        .first()
    )

    if not transaction.category:
        if rule:
            db.delete(rule)
        return 0

    if rule:
        rule.category = transaction.category
    else:
        db.add(CategoryRule(user_id=user_id, match_key=key, category=transaction.category))

    # Spread to the merchant's other transactions (the user's latest intent wins).
    updated = 0
    for tx in _same_merchant(db, user_id, key):
        if tx.id != transaction.id and tx.category != transaction.category:
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


def apply_rules(db: Session, user_id, transactions: list[Transaction]) -> int:
    """Apply the user's saved rules to freshly synced transactions.

    Rule categories take precedence over the provider's generic ones. Does not
    commit — the caller owns the session.
    """
    rules = {
        r.match_key: r.category
        for r in db.query(CategoryRule).filter(CategoryRule.user_id == user_id).all()
    }
    if not rules:
        return 0

    applied = 0
    for tx in transactions:
        key = merchant_match_key(tx.merchant_name, tx.description)
        if key and key in rules:
            tx.category = rules[key]
            applied += 1
    return applied
