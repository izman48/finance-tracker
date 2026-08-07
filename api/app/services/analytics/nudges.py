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

from app.models import AccountRole, CommitmentRule, CommitmentStatus
from app.services.reference import uk_reference as ref

from .common import _d, _load, resolve_roles

# Below this much potential interest a year, the observation is noise.
CASH_DRAG_MIN_PER_YEAR = Decimal("25")

# Two commitments for the same amount and cadence falling this close together
# are the same real-world payment, not two coincidental ones.
DUPLICATE_DAY_TOLERANCE = 2


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

    # --- duplicate commitments: the same payment counted twice ---------------
    # A merchant that renames its descriptor ("ANTHROPIC* CLAUDE SUB" ->
    # "CLAUDE.AI SUBSCRIPTION") gets detected as a second commitment, and the
    # original stays confirmed. Match-key normalisation can't catch a rename —
    # the strings genuinely differ — so surface it instead of merging blind,
    # which could collapse two real payments that happen to agree.
    for group in _duplicate_commitment_groups(db, user):
        first, second = group[0], group[1]
        amount = _d(first.amount)
        extra = amount * (len(group) - 1)
        nudges.append({
            "id": f"duplicate_commitment_{first.id}",
            "rank": 0,  # a wrong number matters more than an optimisation
            "body": (
                f"“{first.label}” and “{second.label}” are both £{amount:,.2f} "
                f"{first.cadence} around {first.next_date:%-d %b}. If they're the same "
                f"payment, £{extra:,.2f}/month is being counted twice."
            ),
            "detail": (
                f"{len(group)} confirmed commitments share an amount (£{amount:,.2f}), a "
                f"cadence ({first.cadence}) and a due date within "
                f"{DUPLICATE_DAY_TOLERANCE} days. That usually means the merchant changed "
                f"its bank descriptor, so the new one was detected while the old one stayed "
                f"confirmed. We don't merge them automatically because two genuinely "
                f"separate payments can look identical. Remove whichever is wrong on the "
                f"commitments page and safe-to-spend corrects itself."
            ),
            "source": None,
            "as_of": None,
        })

    return sorted(nudges, key=lambda n: n["rank"])


def _duplicate_commitment_groups(db: Session, user) -> list[list[CommitmentRule]]:
    """Confirmed commitments that look like the same payment counted twice.

    Grouped on (direction, amount, cadence) — all computed in Python, since
    amount is DEK-encrypted and can never be grouped in SQL.
    """
    rules = (
        db.query(CommitmentRule)
        .filter(
            CommitmentRule.user_id == user.id,
            CommitmentRule.status == CommitmentStatus.CONFIRMED.value,
        )
        .all()
    )
    buckets: dict[tuple, list[CommitmentRule]] = {}
    for rule in rules:
        if rule.next_date is None:
            continue
        buckets.setdefault((rule.direction, _d(rule.amount), rule.cadence), []).append(rule)

    groups = []
    for bucket in buckets.values():
        if len(bucket) < 2:
            continue
        bucket.sort(key=lambda r: r.next_date)
        # Only flag members that actually cluster in time: an annual pair six
        # months apart is two real payments that happen to cost the same.
        cluster = [bucket[0]]
        for rule in bucket[1:]:
            if (rule.next_date - cluster[-1].next_date).days <= DUPLICATE_DAY_TOLERANCE:
                cluster.append(rule)
            else:
                if len(cluster) >= 2:
                    groups.append(cluster)
                cluster = [rule]
        if len(cluster) >= 2:
            groups.append(cluster)
    return groups
