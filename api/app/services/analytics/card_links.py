"""Linking commitments to the credit card they repay (T-08-8).

The summary, forecast and projections tie a commitment to a card only through
the stored `CommitmentRule.card_account_id`. This module fills that link in
for commitments nobody has linked yet. It needs the user's key (labels and
account names are encrypted), so it runs at request time, never in a
migration or a background job.

A link is made only when the label starts with a repayment descriptor for
exactly one of the user's credit cards ("AMEX", "MONZO FLEX"; see
balance_sign.names_card). Anything less certain stays unlinked, and an
unlinked commitment is counted alongside the card's repayment: overstating
outgoings is the safe side. A link set explicitly (`card_link_source` "user",
from the app or an MCP write) is never changed here.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import AccountRole, CommitmentDirection, CommitmentRule
from app.services.balance_sign import names_card

from .common import _load, resolve_roles

AUTO = "auto"
USER = "user"


def credit_card_ids(db: Session, user) -> set:
    """Ids of the user's accounts that currently have the credit role."""
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    return {a.id for a in accounts if roles[a.id] == AccountRole.CREDIT}


def link_card_commitments(db: Session, user) -> None:
    """(Re)make automatic card links; commits only if something changed.

    An auto link is redone when its card is gone or no longer a credit card.
    """
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    cards = [a for a in accounts if roles[a.id] == AccountRole.CREDIT]
    card_ids = {a.id for a in cards}
    rules = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.direction == CommitmentDirection.EXPENSE.value,
        )
        .all()
    )
    changed = False
    for rule in rules:
        if rule.card_link_source == USER:
            continue
        if rule.card_link_source == AUTO and rule.card_account_id in card_ids:
            continue
        named = [a for a in cards if names_card(rule.label, a)]
        link = (named[0].id, AUTO) if len(named) == 1 else (None, None)
        if (rule.card_account_id, rule.card_link_source) != link:
            rule.card_account_id, rule.card_link_source = link
            changed = True
    if changed:
        db.commit()
