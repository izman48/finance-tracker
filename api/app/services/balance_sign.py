"""Money owed on a credit account, with one sign across providers.

Providers report a card's balance with different signs. Amex and Barclaycard
report money owed as a positive number; Monzo reports it as a negative one.
The raw value is stored exactly as the provider sent it (it is DEK-encrypted,
so it can never be migrated), and this module is the only place that
interprets its sign. Every consumer calls `credit_owed`, so a value is
normalised exactly once, at read time, and a later sync cannot double-flip it.

Result: positive = the user owes the card; negative = the card owes the user
(overpaid or refunded); zero = settled or no balance.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from app.models import Account

logger = logging.getLogger(__name__)

# Providers whose raw credit balance is negative when money is owed.
_OWED_IS_NEGATIVE = frozenset({"MONZO"})
# Providers known to report money owed as a positive number (TrueLayer's card
# convention). Listed so an unrecognised provider can be told apart and logged.
_OWED_IS_POSITIVE = frozenset({"AMEX", "AMERICAN EXPRESS", "BARCLAYCARD", "BARCLAYS"})


def _provider_key(account: Account) -> str:
    return (account.provider_name or "").strip().upper()


def credit_owed(account: Account) -> Decimal:
    """Money owed on this credit account (see the module docstring for the sign).

    An unrecognised provider's raw value is returned unchanged, never guessed,
    and a warning names the provider only (no balances, no account names).
    """
    raw = Decimal(str(account.current_balance)) if account.current_balance is not None else Decimal(0)
    provider = _provider_key(account)
    if provider in _OWED_IS_NEGATIVE:
        return -raw
    if provider not in _OWED_IS_POSITIVE:
        logger.warning("Unrecognised credit provider %s: balance sign left as reported", provider)
    return raw
