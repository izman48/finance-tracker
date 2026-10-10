"""A stored commitment-to-card link replaces label matching (T-08-8).

A confirmed expense commitment can store `card_account_id`: the credit card it
repays. The summary, forecast and projections tie a commitment to a card only
through that stored link. Existing commitments are linked lazily, at request
time with the user's key (labels and account names are DEK-encrypted, so no
migration can read them): a label that is a repayment descriptor for exactly
one of the user's credit cards gets an `auto` link. A link the user (or, later,
an MCP write) sets is `user` and the lazy linker never touches it.

Fail safe: while unlinked, or linked to something that can't be a repayment
(not a credit card, no repayment config, a deleted card), the commitment and
the card repayment are both counted. Overstating outgoings is the safe side.
"""
import importlib.util
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.core import user_crypto
from app.models import Account, CommitmentRule
from app.services import analytics_service as svc
from tests.unit.test_card_repayment_once import (
    _account,
    _amex,
    _committed,
    _monzo_flex,
    _setup,
)


def _commitment(db, user, label, amount="400", **link):
    rule = CommitmentRule(
        user_id=user.id, direction="expense", label=label, amount=Decimal(amount),
        cadence="monthly", next_date=svc._today() + timedelta(days=4),
        status="confirmed", **link,
    )
    db.add(rule)
    db.commit()
    return rule


def _reload(db, rule):
    db.expire_all()
    return db.get(CommitmentRule, rule.id)


# Amex 400 owed (one full-balance repayment of 400) + a 400 commitment:
# linked = 400, unlinked = 800.
ONCE, BOTH = Decimal("400"), Decimal("800")


class TestLazyLinking:
    def test_a_descriptor_label_is_linked_to_its_card(self, db_session):
        user = _setup(db_session)
        card = _amex(db_session, user)
        rule = _commitment(db_session, user, "AMEX")
        svc.sync_suggestions(db_session, user)
        rule = _reload(db_session, rule)
        assert (rule.card_account_id, rule.card_link_source) == (card.id, "auto")

    def test_linking_also_happens_when_the_summary_loads(self, db_session):
        """No commitments-page visit needed: the numbers are right straight away."""
        user = _setup(db_session)
        card = _amex(db_session, user)
        rule = _commitment(db_session, user, "AMEX")
        assert _committed(db_session, user) == ONCE
        assert _reload(db_session, rule).card_account_id == card.id

    def test_ambiguous_labels_stay_unlinked(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user, name="Gold")
        _amex(db_session, user, name="Platinum")
        two_cards = _commitment(db_session, user, "AMEX")
        mention = _commitment(db_session, user, "Gym (paid by Amex)", "30")
        svc.sync_suggestions(db_session, user)
        for rule in (two_cards, mention):
            rule = _reload(db_session, rule)
            assert (rule.card_account_id, rule.card_link_source) == (None, None)

    def test_income_is_never_linked(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user)
        rule = _commitment(db_session, user, "AMEX CASHBACK", "25")
        rule.direction = "income"
        db_session.commit()
        svc.sync_suggestions(db_session, user)
        assert _reload(db_session, rule).card_account_id is None


class TestAutoLinksFollowTheLabel:
    """sec review on #98: an auto link must not outlive the label that made it."""

    def test_relabelling_away_from_the_card_counts_both_again(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user)
        rule = _commitment(db_session, user, "AMEX")
        assert _committed(db_session, user) == ONCE
        rule = _reload(db_session, rule)
        rule.label = "Gym"
        db_session.commit()
        assert _committed(db_session, user) == BOTH
        rule = _reload(db_session, rule)
        assert (rule.card_account_id, rule.card_link_source) == (None, None)

    def test_a_second_card_of_the_provider_unlinks_the_auto_link(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user, name="Gold")
        rule = _commitment(db_session, user, "AMEX")
        svc.sync_suggestions(db_session, user)
        _amex(db_session, user, name="Platinum")
        svc.sync_suggestions(db_session, user)
        assert _reload(db_session, rule).card_account_id is None


class TestCountingUsesOnlyTheStoredLink:
    def test_a_user_link_ties_a_commitment_whatever_its_label(self, db_session):
        user = _setup(db_session)
        card = _amex(db_session, user)
        _commitment(db_session, user, "Card bill", card_account_id=card.id, card_link_source="user")
        assert _committed(db_session, user) == ONCE

    def test_a_user_unlink_counts_both_even_for_a_descriptor_label(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user)
        rule = _commitment(db_session, user, "AMEX", card_account_id=None, card_link_source="user")
        assert _committed(db_session, user) == BOTH
        assert _reload(db_session, rule).card_link_source == "user"

    def test_the_linker_never_overwrites_a_user_link(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user)
        flex = _monzo_flex(db_session, user)
        rule = _commitment(db_session, user, "AMEX", card_account_id=flex.id, card_link_source="user")
        svc.sync_suggestions(db_session, user)
        svc.get_summary(db_session, user)
        rule = _reload(db_session, rule)
        assert (rule.card_account_id, rule.card_link_source) == (flex.id, "user")


class TestFailSafeWhileUnlinked:
    def test_unlinked_counts_both(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user)
        _commitment(db_session, user, "DD to Amex")
        assert _committed(db_session, user) == BOTH

    def test_link_to_an_account_that_is_not_a_credit_card(self, db_session):
        user = _setup(db_session)
        _amex(db_session, user)
        current = db_session.query(Account).filter(
            Account.user_id == user.id, Account.account_type == "TRANSACTION"
        ).one()
        _commitment(db_session, user, "Card bill", card_account_id=current.id, card_link_source="user")
        assert _committed(db_session, user) == BOTH

    def test_link_to_a_card_without_a_repayment_config(self, db_session):
        user = _setup(db_session)
        card = _amex(db_session, user, configured=False)
        _commitment(db_session, user, "Card bill", card_account_id=card.id, card_link_source="user")
        # No repayment events for the card, so the commitment alone counts.
        assert _committed(db_session, user) == Decimal("400")
        f = svc.get_forecast(db_session, user, horizon="30")
        kinds = [e["kind"] for p in f["timeline"] for e in p["events"]]
        assert "expense" in kinds

    def test_link_to_a_deleted_card(self, db_session):
        user = _setup(db_session)
        gone = _account(db_session, user, "CREDIT_CARD", "0", "Old", "American Express")
        _amex(db_session, user)
        rule = _commitment(db_session, user, "Card bill", card_account_id=gone.id, card_link_source="user")
        db_session.delete(gone)
        db_session.commit()
        assert _committed(db_session, user) == BOTH
        # The FK nulls the link in Postgres; either way it is not a tie.
        assert _reload(db_session, rule).card_link_source == "user"

    def test_an_auto_link_to_a_deleted_card_is_redone(self, db_session):
        user = _setup(db_session)
        gone = _account(db_session, user, "CREDIT_CARD", "0", "Old", "American Express")
        card = _amex(db_session, user)
        rule = _commitment(db_session, user, "AMEX", card_account_id=gone.id, card_link_source="auto")
        db_session.delete(gone)
        db_session.commit()
        assert _committed(db_session, user) == ONCE
        assert _reload(db_session, rule).card_account_id == card.id


class TestProjectionsUseTheLink:
    def test_a_linked_commitment_is_not_a_projection_bill(self, db_session):
        user = _setup(db_session)
        card = _amex(db_session, user)
        _commitment(db_session, user, "Card bill", card_account_id=card.id, card_link_source="user")
        assert svc.derived_contribution(db_session, user)["bills_monthly"] == Decimal("0.00")


# --- the migration: schema only, runs with no user key -------------------


_API = Path(__file__).resolve().parents[2]
_MIGRATION = next((_API / "migrations" / "versions").glob("*_add_commitment_card_link.py"))
_spec = importlib.util.spec_from_file_location("add_commitment_card_link", _MIGRATION)
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def _without_user_key(db, step):
    token = user_crypto.current_dek.set(None)
    try:
        _run(db, step)
    finally:
        user_crypto.current_dek.reset(token)


def _columns(db):
    return {c["name"] for c in inspect(db.connection()).get_columns("commitment_rules")}


def _run(db, step):
    with Operations.context(MigrationContext.configure(db.connection())):
        step()
    db.commit()


class TestMigration:
    def test_down_up_without_a_user_key_keeps_existing_rows(self, db_session):
        user = _setup(db_session)
        _commitment(db_session, user, "Rent", "950")
        count = "SELECT count(*) FROM commitment_rules"
        assert {"card_account_id", "card_link_source"} <= _columns(db_session)
        _without_user_key(db_session, migration.downgrade)
        assert not {"card_account_id", "card_link_source"} & _columns(db_session)
        _without_user_key(db_session, migration.upgrade)
        assert db_session.execute(text(count)).scalar() == 1
        assert {"card_account_id", "card_link_source"} <= _columns(db_session)
        indexes = {i["name"] for i in inspect(db_session.connection()).get_indexes("commitment_rules")}
        assert "ix_commitment_rules_card_account_id" in indexes
        fks = inspect(db_session.connection()).get_foreign_keys("commitment_rules")
        card_fk = [fk for fk in fks if fk["constrained_columns"] == ["card_account_id"]]
        assert card_fk and card_fk[0]["referred_table"] == "accounts"
        assert card_fk[0]["options"].get("ondelete") == "SET NULL"

    def test_the_migration_chain_has_one_head(self):
        cfg = Config(str(_API / "alembic.ini"))
        cfg.set_main_option("script_location", str(_API / "migrations"))
        assert len(ScriptDirectory.from_config(cfg).get_heads()) == 1
