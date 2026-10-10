"""Money owed on a credit account, with one sign across providers.

Providers report a card's balance with different signs: Amex reports money
owed as a positive number, Monzo as a negative one. The raw value is stored
exactly as the provider sent it (it is DEK-encrypted, so it can never be
migrated), and this module is the only place that interprets its sign. Every
consumer calls `credit_owed`, so a value is normalised exactly once, at read
time, and a later sync cannot double-flip it.

Result: positive = the user owes the card; negative = the card owes the user
(overpaid or refunded); zero = settled or no balance.

Only providers whose sign has been observed on real data are listed. Any
other provider falls back to abs(): overstating a debt is safe, hiding one is
not, so an unverified provider's overpayment is counted as owed.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from app.models import Account

logger = logging.getLogger(__name__)

# Observed 2026-10-10 on connected accounts (signs only):
_OWED_IS_NEGATIVE = frozenset({"MONZO"})  # Monzo credit card: owed < 0
_OWED_IS_POSITIVE = frozenset({"AMEX", "AMERICAN EXPRESS"})  # Amex card: owed > 0

# How each provider's card repayment shows up in a commitment's label (a bank
# descriptor or the user's own name for it). Specific to the card, so a
# commitment can be tied to one account; generic phrases ("credit card") are
# deliberately absent. "american exp" because banks truncate the descriptor.
_REPAYMENT_DESCRIPTORS = {
    "AMEX": ("amex", "american exp"),
    "AMERICAN EXPRESS": ("amex", "american exp"),
    "MONZO": ("monzo flex",),
    "BARCLAYCARD": ("barclaycard",),
    "BARCLAYS": ("barclaycard",),
}

# Providers already warned about in this process, so one unverified provider
# doesn't log on every read (summary, repayments, each net-worth point).
_warned: set[str] = set()


def _provider_key(account: Account) -> str:
    return (account.provider_name or "").strip().upper()


def credit_owed(account: Account) -> Decimal:
    """Money owed on this credit account (see the module docstring for the sign)."""
    raw = Decimal(str(account.current_balance)) if account.current_balance is not None else Decimal(0)
    provider = _provider_key(account)
    if provider in _OWED_IS_NEGATIVE:
        return -raw
    if provider in _OWED_IS_POSITIVE:
        return raw
    if provider not in _warned:
        _warned.add(provider)
        logger.warning("Credit balance sign not verified, counting it as owed: %s", provider)
    return abs(raw)


def names_card(text: str, account: Account) -> bool:
    """True if `text` (a commitment label) names this credit account's card
    by one of its provider's specific repayment descriptors."""
    lowered = (text or "").lower()
    return any(d in lowered for d in _REPAYMENT_DESCRIPTORS.get(_provider_key(account), ()))
