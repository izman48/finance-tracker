"""UK reference facts used by the nudge engine.

Every value here is a published fact or a curated snapshot with an explicit
`as_of` — the UI must always render the date next to the number. Update by
editing this file and deploying; the git history is the audit trail.
"""
from datetime import date
from decimal import Decimal

# FSCS deposit protection: per person, per banking licence.
FSCS_LIMIT = Decimal("85000")
FSCS_SOURCE = "FSCS deposit protection limit (fscs.org.uk)"

# Best widely-available easy-access savings rate (AER %), curated from public
# best-buy tables. Used only to size "what idle cash could earn" arithmetic —
# we never recommend a product, and we don't know the user's actual rate.
BEST_EASY_ACCESS_RATE_PCT = Decimal("4.5")
BEST_EASY_ACCESS_AS_OF = date(2026, 7, 1)
BEST_EASY_ACCESS_SOURCE = "public best-buy tables (curated snapshot)"

# Brands documented as sharing one FSCS banking licence → canonical licence
# name. Deliberately only well-known pairs; an absent brand is treated as its
# own licence, and the nudge always carries the shared-licence caveat because
# this map cannot be exhaustive.
FSCS_LICENCE_GROUPS: dict[str, str] = {
    "hsbc": "HSBC UK Bank",
    "first direct": "HSBC UK Bank",
    "halifax": "Bank of Scotland",
    "bank of scotland": "Bank of Scotland",
    "birmingham midshires": "Bank of Scotland",
    "santander": "Santander UK",
    "cahoot": "Santander UK",
    "the co-operative bank": "The Co-operative Bank",
    "co-operative bank": "The Co-operative Bank",
    "smile": "The Co-operative Bank",
}


def fscs_licence(provider_name: str) -> str:
    """The FSCS licence a provider brand most likely belongs to (best effort)."""
    return FSCS_LICENCE_GROUPS.get(provider_name.strip().lower(), provider_name.strip())
