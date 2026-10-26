"""Categorization rule engine.

Rules (exact / contains / regex, optionally grouped into packs) map transaction
text to categories. Manual per-transaction categories are "locked" and never
overwritten. When several rules match, precedence is deliberately boring:

  1. the user's own rules (learned/manual) beat imported pack rules
  2. exact beats contains beats regex
  3. longer patterns beat shorter ones
"""
import functools
import logging
from datetime import datetime, timezone

import re2

from sqlalchemy.orm import Session, joinedload

from app.models import Account, CategoryRule, Transaction, merchant_match_key

logger = logging.getLogger(__name__)

# Regexes are user-supplied (and importable from other users); cap complexity.
MAX_PATTERN_LENGTH = 200
_MATCH_TYPE_RANK = {"exact": 0, "contains": 1, "regex": 2}


# TrueLayer's `transaction_category` values. They are transaction *types*, not
# spending categories, so none is ever stored as one (T-08-1).
PROVIDER_TRANSACTION_TYPES = frozenset({
    "ATM", "BILL_PAYMENT", "CASH", "CASHBACK", "CHEQUE", "CORRECTION", "CREDIT",
    "DEBIT", "DIRECT_DEBIT", "DIVIDEND", "FEE", "FEE_CHARGE", "INTEREST", "OTHER",
    "PURCHASE", "STANDING_ORDER", "TRANSFER", "UNKNOWN",
})
INCOME_CATEGORY = "Income"
TRANSFERS_CATEGORY = "Transfers"


def category_from_provider(raw: str | None, transaction_type) -> str | None:
    """The category to store for a provider transaction type.

    TRANSFER -> Transfers (still a transfer to the spending lenses); a credit of
    a known type -> Income; anything else, including a type we have never seen,
    -> None ("Uncategorized"). Income is decided by the transaction_type column,
    never by the provider string, so a debit can never become Income.
    """
    kind = (raw or "").strip().upper()
    if kind == "TRANSFER":
        return TRANSFERS_CATEGORY
    is_credit = getattr(transaction_type, "value", transaction_type) == "credit"
    if is_credit and kind in PROVIDER_TRANSACTION_TYPES - {"UNKNOWN"}:
        return INCOME_CATEGORY
    return None


def validate_pattern(pattern: str, match_type: str) -> str | None:
    """Return an error message if the pattern is unusable, else None."""
    if not pattern or not pattern.strip():
        return "Pattern is empty"
    if len(pattern) > MAX_PATTERN_LENGTH:
        return f"Pattern longer than {MAX_PATTERN_LENGTH} characters"
    if match_type == "regex" and _compiled(pattern) is None:
        return UNSUPPORTED_REGEX
    return None


# Regex rules run on RE2, a linear-time engine (T-12-10b, lead decision on
# #248): no pattern can backtrack, whatever its shape, so a user's or a
# shared pack's regex can't stall a request. RE2 has no back-references,
# look-arounds or conditional groups; such patterns are refused when written
# and skipped when loaded. Errors are never logged by RE2 itself (the
# pattern is user text), and matching never captures.
UNSUPPORTED_REGEX = (
    "Invalid or unsupported regex: nilu matches with a linear-time engine, "
    "so back-references, look-arounds and conditional groups aren't allowed"
)
_RE2_OPTIONS = re2.Options()
_RE2_OPTIONS.case_sensitive = False
_RE2_OPTIONS.log_errors = False
_RE2_OPTIONS.never_capture = True


# Shown on the Rules page for a stored regex RE2 can't run (sec-1 on #248).
CANT_RUN_REASON = (
    "Look-arounds and back-references aren't supported, so this rule can't run. "
    "Delete it and add it again without them."
)


def cant_run_reason(rule: CategoryRule) -> str | None:
    """Why a stored rule never matches, or None when it runs."""
    if rule.match_type == "regex" and _compiled(rule.pattern.strip()[:MAX_PATTERN_LENGTH]) is None:
        return CANT_RUN_REASON
    return None


@functools.lru_cache(maxsize=512)
def _compiled(pattern: str):
    """The RE2 program for a regex rule, or None if RE2 can't run it. Cached
    like `re`'s own pattern cache, so a rule compiles once per process."""
    try:
        return re2.compile(pattern, options=_RE2_OPTIONS)
    except re2.error:
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
        compiled = _compiled(pattern[:MAX_PATTERN_LENGTH])
        return compiled is not None and any(compiled.search(f) for f in fields)
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
    # A regex stored before RE2 that it can't run is skipped (it would match
    # nothing anyway); the count only is logged, never the pattern.
    runnable = [r for r in rules if r.match_type != "regex" or _compiled(r.pattern.strip()[:MAX_PATTERN_LENGTH])]
    if len(runnable) < len(rules):
        skipped = len(rules) - len(runnable)
        logger.warning("Skipped %d stored regex rule(s) the matching engine can't run", skipped)
    runnable.sort(key=_precedence)
    return runnable


def winning_rule(rules: list[CategoryRule], tx: Transaction) -> CategoryRule | None:
    """The rule that sets a transaction's category, or None. `rules` must be
    pre-sorted by active_rules()."""
    return next((rule for rule in rules if _rule_matches(rule, tx)), None)


def categorize(rules: list[CategoryRule], tx: Transaction) -> str | None:
    """Best-matching category for a transaction, or None. `rules` must be
    pre-sorted by active_rules()."""
    rule = winning_rule(rules, tx)
    return rule.category if rule else None


def counts_as_for(rules: list[CategoryRule], tx: Transaction) -> str | None:
    """Best-matching counts_as reclassification (transfer/card_payment/
    spending), or None. `rules` must be pre-sorted by active_rules()."""
    for rule in rules:
        if rule.counts_as and _rule_matches(rule, tx):
            return rule.counts_as
    return None


def apply_rules(db: Session, user_id, transactions: list[Transaction]) -> int:
    """Apply the user's rules to the given transactions.

    Each field has its own lock: category respects category_locked, and
    counts_as_override respects counts_as_locked (hand-set always wins). An
    unlocked counts_as_override is RECOMPUTED from the current rules — set,
    changed, or cleared back to automatic when no rule claims it anymore — so
    editing or deleting a rule actually corrects history on the next run.
    Used for newly synced transactions and retroactive runs. Does not commit —
    the caller owns the session. Returns the number of transactions changed.
    """
    # No early-return on empty rules: deleting the last rule must still clear
    # the unlocked counts_as stamps it left behind on the next run.
    rules = active_rules(db, user_id)

    changed = 0
    for tx in transactions:
        tx_changed = False
        if not tx.category_locked:
            category = categorize(rules, tx)
            if category and category != tx.category:
                tx.category = category
                tx_changed = True
        if not tx.counts_as_locked:
            counts = counts_as_for(rules, tx)
            if counts != tx.counts_as_override:
                tx.counts_as_override = counts
                tx_changed = True
        if tx_changed:
            changed += 1
    if changed:
        logger.info(f"Rules categorized {changed} transactions for user {user_id}")
    return changed


def apply_rules_to_all(db: Session, user_id) -> int:
    """Retroactively run the rule engine over every transaction.

    Loads all of them (not just category-unlocked): a hand-categorized
    transaction can still receive a rule's counts_as — the per-field locks
    inside apply_rules decide what may change.
    """
    return apply_rules(db, user_id, user_transactions(db, user_id))


def recategorize_all(db: Session, user_id) -> list[dict]:
    """apply_rules_to_all, returning what it changed: one {"id", "before",
    "after"} category record per transaction it changed (counts_as is
    recomputed from the rules on every run, so it needs no record). An undo
    hands these to `restore_categories` (sec on #256). Does not commit."""
    transactions = user_transactions(db, user_id)
    before = {tx.id: (tx.category, tx.counts_as_override) for tx in transactions}
    apply_rules(db, user_id, transactions)
    return [
        {"id": str(tx.id), "before": before[tx.id][0], "after": tx.category}
        for tx in transactions if (tx.category, tx.counts_as_override) != before[tx.id]
    ]


def set_by_rule_since(rules: list[CategoryRule], transactions: list[Transaction], rule: CategoryRule,
                      since: datetime, recorded_ids: set[str]) -> list[Transaction]:
    """The transactions `rule` categorised after `since` (its edit), found by
    re-matching rather than a stored link (sec on T-16-2). Call it while the
    rule is still as edited. A transaction counts only when all hold: it was
    inserted after the edit (row `created_at`, never `transaction_date`), it
    isn't in the edit's undo record, it isn't locked, it still has the rule's
    category, and this rule wins it (`rules` pre-sorted by active_rules(); a
    higher-precedence rule with the same category excludes it)."""
    return [
        tx for tx in transactions
        if _inserted_after(tx, since)
        and str(tx.id) not in recorded_ids
        and not tx.category_locked
        and tx.category == rule.category
        and getattr(winning_rule(rules, tx), "id", None) == rule.id
    ]


def _inserted_after(tx: Transaction, since: datetime) -> bool:
    if tx.created_at is None:
        return False
    return _as_utc(tx.created_at) > _as_utc(since)


def _as_utc(moment: datetime) -> datetime:
    """SQLite hands back naive datetimes; the columns are stored as UTC."""
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def restore_categories(db: Session, user_id, transactions: list[Transaction], changed: list[dict],
                       set_since: list[Transaction]) -> None:
    """Undo a rule edit's effect on history, after the rule itself is
    restored. The categories recorded by `recategorize_all` go back where the
    transaction still has the category that run set and isn't locked (a
    category set by hand, or changed since, is left alone). The ones
    `set_by_rule_since` found are cleared. Then the rules run again, so a
    cleared one gets the category the restored rules give, or stays None
    (Uncategorised: spending overstated, never hidden). Does not commit."""
    records = {r["id"]: r for r in changed}
    for tx in transactions:
        record = records.get(str(tx.id))
        if record and not tx.category_locked and tx.category == record["after"]:
            tx.category = record["before"]
    for tx in set_since:
        tx.category = None
    apply_rules(db, user_id, transactions)


def user_transactions(db: Session, user_id) -> list[Transaction]:
    """All of the user's transactions (scoped by account owner)."""
    return db.query(Transaction).join(Account).filter(Account.user_id == user_id).all()


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

    # Patterns are encrypted at rest, so the "existing learned rule for this
    # merchant" lookup compares in Python over the user's learned rules.
    rule = next(
        (
            r
            for r in db.query(CategoryRule).filter(
                CategoryRule.user_id == user_id,
                CategoryRule.match_type == "exact",
                CategoryRule.source == "learned",
            )
            if r.pattern == key
        ),
        None,
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

    merchant_name/description are encrypted at rest, so the match runs in
    Python over the user's (decrypted) transactions rather than in SQL.
    """
    txns = (
        db.query(Transaction)
        .join(Account)
        .filter(Account.user_id == user_id)
        .all()
    )
    return [
        tx for tx in txns if merchant_match_key(tx.merchant_name, tx.description) == key
    ]
