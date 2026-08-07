"""Reference drift, card-settlement detection, and duplicate commitments.

The descriptors here are real shapes seen in production, where each of these
bugs was found: a mandate reference that rolls, an Amex settlement whose
descriptor is truncated, and a merchant that renamed itself into a second
commitment.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.models import AccountRole
from app.services.analytics.commitments import _match_key, _normalise_merchant
from app.services.analytics.common import is_card_settlement
from app.services.analytics.nudges import _duplicate_commitment_groups


class TestReferenceDrift:
    def test_rolling_mandate_reference_keys_identically(self):
        """EE rolls the Q-reference between payments; both are the same bill."""
        july = _match_key("expense", "EE LIMITED Q42181371737681503 DDR")
        august = _match_key("expense", "EE LIMITED Q42181371746583221 DDR")
        assert july == august == "expense:ee limited ddr"

    def test_other_real_reference_formats(self):
        for a, b in [
            ("IKANO BANK UUID-12331371342 DDR", "IKANO BANK UUID-99887766554 DDR"),
            ("COMMUNITYFIBRE LTD A1539913 DDR", "COMMUNITYFIBRE LTD A1539914 DDR"),
            ("D&G APPLIANCE CARE D4V20000295 DDR", "D&G APPLIANCE CARE D4V20000296 DDR"),
        ]:
            assert _match_key("expense", a) == _match_key("expense", b), a

    def test_short_digits_in_a_name_are_preserved(self):
        """The conservative half: real names keep their short digit groups."""
        assert "o2" in _normalise_merchant("O2 UK").lower()
        assert "monzo123" in _normalise_merchant("MONZO123").lower()
        # The flat number in a rent reference is part of the name, not a ref.
        assert "1606landmarke" in _normalise_merchant("RENT 1606LANDMARKE FT").lower()

    def test_unrelated_merchants_still_differ(self):
        assert _match_key("expense", "TESCO") != _match_key("expense", "GREGGS PLC")

    def test_all_reference_token_falls_back_to_raw(self):
        assert _normalise_merchant("123456789") == "123456789"

    def test_stale_stored_key_still_dedupes_via_label(self):
        """A manual rule's stored key is never rewritten, so it can go stale
        after a normalisation change. Detection must still recognise it, or it
        re-adds a commitment the user already has."""
        rule = _rule("EE LIMITED Q42181371737681503 DDR", "68.50", date(2026, 9, 7))
        rule.match_key = "expense:ee limited q42181371737681503 ddr"  # pre-change key

        existing = {rule.match_key}
        existing |= {_match_key(rule.direction, rule.label)}

        # What today's detection would group this month's payment under.
        assert _match_key("expense", "EE LIMITED Q42181371746583221 DDR") in existing


class TestCardSettlement:
    def _tx(self, desc):
        return SimpleNamespace(description=desc, merchant_name=None, transaction_type="debit")

    def test_truncated_amex_descriptor_is_a_settlement(self):
        """The bug: banks truncate to 'AMERICAN EXP', so the full word missed."""
        tx = self._tx("AMERICAN EXP 3773 PB945227708021965 FT")
        assert is_card_settlement(tx, AccountRole.SPENDING) is True

    def test_untruncated_form_still_matches(self):
        assert is_card_settlement(self._tx("AMERICAN EXPRESS PAYMENT"), AccountRole.SPENDING)

    def test_ordinary_spending_is_not_a_settlement(self):
        assert is_card_settlement(self._tx("TESCO PAYAT PUMP 3"), AccountRole.SPENDING) is False


def _rule(label, amount, next_date, cadence="monthly", direction="expense"):
    return SimpleNamespace(
        id=uuid4(), label=label, amount=Decimal(amount), next_date=next_date,
        cadence=cadence, direction=direction,
    )


class _FakeDb:
    def __init__(self, rules):
        self._rules = rules

    def query(self, *_):
        return self

    def filter(self, *_, **__):
        return self

    def all(self):
        return self._rules


class TestDuplicateCommitments:
    def test_renamed_merchant_is_flagged(self):
        rules = [
            _rule("ANTHROPIC* CLAUDE SUB SAN FRANCISCO", "18.00", date(2026, 8, 16)),
            _rule("CLAUDE.AI SUBSCRIPTION SAN FRANCISCO", "18.00", date(2026, 8, 16)),
        ]
        groups = _duplicate_commitment_groups(_FakeDb(rules), SimpleNamespace(id=uuid4()))
        assert len(groups) == 1 and len(groups[0]) == 2

    def test_same_amount_far_apart_is_not_a_duplicate(self):
        """Two real £18 bills at opposite ends of the month are not one bill."""
        rules = [
            _rule("GYM", "18.00", date(2026, 8, 2)),
            _rule("INSURANCE", "18.00", date(2026, 8, 25)),
        ]
        assert _duplicate_commitment_groups(_FakeDb(rules), SimpleNamespace(id=uuid4())) == []

    def test_different_amounts_are_not_duplicates(self):
        rules = [
            _rule("APPLE.COM/UK LONDON", "11.99", date(2026, 8, 14)),
            _rule("APPLE.COM/BILL HOLLYHILL", "12.49", date(2026, 8, 14)),
        ]
        assert _duplicate_commitment_groups(_FakeDb(rules), SimpleNamespace(id=uuid4())) == []

    def test_single_commitment_is_never_flagged(self):
        rules = [_rule("OCTOPUS ENERGY", "147.49", date(2026, 9, 1))]
        assert _duplicate_commitment_groups(_FakeDb(rules), SimpleNamespace(id=uuid4())) == []
