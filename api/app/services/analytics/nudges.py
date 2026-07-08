"""Nudges: honest, dismissible observations for the Cashflow feed.

v1 needs only current balances plus published constants (reference/uk_reference)
— no background job, no new data. Everything is computed request-time in Python
(balances come off encrypted columns via the ORM; never aggregate in SQL).

The FCA line: every nudge states a fact and shows its arithmetic + source +
as-of date. None of them says "you should…" or names a product to move to.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import AccountRole
from app.services.reference import uk_reference as ref

from .common import _d, _load, resolve_roles

# Below this much potential interest a year, the observation is noise.
CASH_DRAG_MIN_PER_YEAR = Decimal("25")


def get_nudges(db: Session, user) -> list[dict]:
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)

    savings_total = Decimal(0)
    # Positive deposit balances by (best-effort) FSCS licence. Negative
    # balances are borrowing, not deposits — they don't offset protection.
    by_licence: dict[str, dict] = {}
    for acc in accounts:
        role = roles.get(acc.id)
        if role not in (AccountRole.SPENDING, AccountRole.SAVINGS):
            continue
        balance = _d(acc.current_balance)
        if balance <= 0:
            continue
        if role == AccountRole.SAVINGS:
            savings_total += balance
        licence = ref.fscs_licence(acc.provider_name or "")
        g = by_licence.setdefault(licence, {"total": Decimal(0), "providers": set()})
        g["total"] += balance
        g["providers"].add(acc.provider_name or licence)

    nudges: list[dict] = []

    # --- cash drag: what idle savings could earn at the curated benchmark ----
    rate = ref.BEST_EASY_ACCESS_RATE_PCT
    potential = (savings_total * rate / 100).quantize(Decimal("1"))
    if potential >= CASH_DRAG_MIN_PER_YEAR:
        nudges.append({
            "id": "cash_drag",
            "rank": 1,
            "body": (
                f"£{savings_total:,.0f} sits in savings accounts. If it's earning little or "
                f"nothing, that's roughly £{potential:,.0f}/yr of interest at the best "
                f"easy-access rate ({rate}% as of {ref.BEST_EASY_ACCESS_AS_OF:%-d %b %Y})."
            ),
            "detail": (
                f"£{savings_total:,.0f} × {rate}% = £{potential:,.0f}/yr. We can't see your "
                f"actual rate, so this compares against 0% — your real gap may be smaller. "
                f"Benchmark: {ref.BEST_EASY_ACCESS_SOURCE}."
            ),
            "source": ref.BEST_EASY_ACCESS_SOURCE,
            "as_of": ref.BEST_EASY_ACCESS_AS_OF,
        })

    # --- FSCS exposure: deposits above the protected limit per licence -------
    for licence, g in sorted(by_licence.items(), key=lambda kv: kv[1]["total"], reverse=True):
        if g["total"] <= ref.FSCS_LIMIT:
            continue
        over = g["total"] - ref.FSCS_LIMIT
        names = " + ".join(sorted(g["providers"]))
        nudges.append({
            "id": f"fscs_{licence.lower().replace(' ', '_')}",
            "rank": 2,
            "body": (
                f"You hold £{g['total']:,.0f} with {names}. FSCS protects £{ref.FSCS_LIMIT:,.0f} "
                f"per person per banking licence, so about £{over:,.0f} of it sits above the "
                f"protected limit."
            ),
            "detail": (
                f"£{g['total']:,.0f} − £{ref.FSCS_LIMIT:,.0f} = £{over:,.0f} above the limit. "
                f"Protection applies per banking licence, and some brands share one — we group "
                f"the well-known cases but can't be exhaustive, so check with your bank. "
                f"Source: {ref.FSCS_SOURCE}."
            ),
            "source": ref.FSCS_SOURCE,
            "as_of": None,
        })

    return sorted(nudges, key=lambda n: n["rank"])
