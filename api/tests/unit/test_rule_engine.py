"""Unit tests for the categorization rule engine."""
import uuid
from datetime import datetime, timedelta, timezone

from app.models import CategoryRule, Transaction
from app.services.categorization import (
    MAX_PATTERN_LENGTH,
    _precedence,
    _rule_matches,
    categorize,
    set_by_rule_since,
    validate_pattern,
)


def make_tx(merchant=None, description=""):
    return Transaction(
        id=uuid.uuid4(),
        merchant_name=merchant,
        description=description,
        category=None,
        category_locked=False,
    )


def make_rule(pattern, match_type="contains", match_field="any", category="Food", source="manual", enabled=True):
    return CategoryRule(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        pattern=pattern,
        match_type=match_type,
        match_field=match_field,
        category=category,
        source=source,
        enabled=enabled,
    )


class TestMatching:
    def test_contains_is_case_insensitive(self):
        rule = make_rule("deliveroo")
        assert _rule_matches(rule, make_tx(merchant="DELIVEROO LONDON"))
        assert _rule_matches(rule, make_tx(description="Card payment Deliveroo*123"))
        assert not _rule_matches(rule, make_tx(merchant="Tesco"))

    def test_exact_requires_full_field(self):
        rule = make_rule("netflix", match_type="exact")
        assert _rule_matches(rule, make_tx(merchant="Netflix"))
        assert not _rule_matches(rule, make_tx(merchant="Netflix.com Ltd"))

    def test_field_restriction(self):
        rule = make_rule("uber", match_field="merchant")
        assert _rule_matches(rule, make_tx(merchant="Uber"))
        assert not _rule_matches(rule, make_tx(merchant="Bolt", description="not uber"))

    def test_regex(self):
        rule = make_rule(r"^AMZN.*MKTP", match_type="regex")
        assert _rule_matches(rule, make_tx(description="AMZN Digital MKTP UK"))
        assert not _rule_matches(rule, make_tx(description="PAYPAL AMZN MKTP"))

    def test_invalid_regex_never_matches(self):
        rule = make_rule("([unclosed", match_type="regex")
        assert not _rule_matches(rule, make_tx(description="([unclosed"))


class TestValidation:
    def test_rejects_bad_regex(self):
        assert validate_pattern("([", "regex") is not None

    def test_rejects_too_long(self):
        assert validate_pattern("x" * (MAX_PATTERN_LENGTH + 1), "contains") is not None

    def test_accepts_normal_patterns(self):
        assert validate_pattern("deliveroo", "contains") is None
        assert validate_pattern(r"^AMZN.*", "regex") is None


class TestPrecedence:
    def test_own_rules_beat_imported(self):
        own = make_rule("deliveroo", category="Eating out", source="learned")
        imported = make_rule("deliveroo", category="Food shopping", source="imported")
        ordered = sorted([imported, own], key=_precedence)
        assert ordered[0] is own
        assert categorize(ordered, make_tx(merchant="Deliveroo")) == "Eating out"

    def test_exact_beats_contains(self):
        exact = make_rule("deliveroo", match_type="exact", category="Exact")
        contains = make_rule("deliveroo", match_type="contains", category="Contains")
        ordered = sorted([contains, exact], key=_precedence)
        assert categorize(ordered, make_tx(merchant="Deliveroo")) == "Exact"

    def test_longer_pattern_beats_shorter(self):
        short = make_rule("tesco", category="Groceries")
        long = make_rule("tesco fuel", category="Transport")
        ordered = sorted([short, long], key=_precedence)
        assert categorize(ordered, make_tx(merchant="TESCO FUEL 0392")) == "Transport"

    def test_no_match_returns_none(self):
        rules = sorted([make_rule("spotify")], key=_precedence)
        assert categorize(rules, make_tx(merchant="Netflix")) is None


class TestSetByRuleSince:
    """T-16-2: which transactions an edited rule categorised after its edit
    (sec's five conditions; re-matched at undo time, no stored link)."""

    EDIT_AT = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)

    def synced(self, merchant, category, *, at=None, locked=False):
        tx = make_tx(merchant=merchant)
        tx.category, tx.category_locked = category, locked
        tx.created_at = at or self.EDIT_AT + timedelta(hours=1)
        return tx

    def found(self, rules, rule, txs, recorded=()):
        rules = sorted(rules, key=_precedence)
        return set_by_rule_since(rules, txs, rule, self.EDIT_AT, {str(t.id) for t in recorded})

    def test_a_later_transaction_the_rule_wins_is_found(self):
        rule = make_rule("amazon", category="Shopping")
        tx = self.synced("AMAZON", "Shopping")
        assert self.found([rule], rule, [tx]) == [tx]

    def test_inserted_at_or_before_the_edit_is_not(self):
        rule = make_rule("amazon", category="Shopping")
        txs = [self.synced("AMAZON", "Shopping", at=self.EDIT_AT),
               self.synced("AMAZON", "Shopping", at=self.EDIT_AT - timedelta(days=3))]
        assert self.found([rule], rule, txs) == []

    def test_a_naive_timestamp_is_read_as_utc(self):
        """SQLite returns naive datetimes; Postgres aware ones."""
        rule = make_rule("amazon", category="Shopping")
        tx = self.synced("AMAZON", "Shopping", at=(self.EDIT_AT + timedelta(seconds=1)).replace(tzinfo=None))
        assert self.found([rule], rule, [tx]) == [tx]

    def test_one_in_the_undo_record_is_not(self):
        rule = make_rule("amazon", category="Shopping")
        tx = self.synced("AMAZON", "Shopping")
        assert self.found([rule], rule, [tx], recorded=[tx]) == []

    def test_a_locked_one_is_not(self):
        rule = make_rule("amazon", category="Shopping")
        assert self.found([rule], rule, [self.synced("AMAZON", "Shopping", locked=True)]) == []

    def test_one_in_another_category_is_not(self):
        rule = make_rule("amazon", category="Shopping")
        assert self.found([rule], rule, [self.synced("AMAZON", "Gifts")]) == []

    def test_a_higher_precedence_rule_with_the_same_category_excludes_it(self):
        """sec: the rule matching is not enough; it must win."""
        rule = make_rule("amazon", match_type="regex", category="Shopping")
        better = make_rule("AMAZON", match_type="exact", category="Shopping")
        assert self.found([rule, better], rule, [self.synced("AMAZON", "Shopping")]) == []

    def test_a_rule_that_is_not_active_wins_nothing(self):
        """An edit that switched the rule off: it isn't in the active rules."""
        rule = make_rule("amazon", category="Shopping")
        assert self.found([], rule, [self.synced("AMAZON", "Shopping")]) == []
