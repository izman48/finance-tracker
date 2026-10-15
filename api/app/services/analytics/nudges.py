"""Nudges: honest, dismissible observations for the Cashflow feed.

v1 needs only current balances plus published constants (reference/uk_reference)
— no background job, no new data. Everything is computed request-time in Python
(balances come off encrypted columns via the ORM; never aggregate in SQL).

The FCA line: every nudge states a fact and shows its arithmetic + source +
as-of date. None of them says "you should…" or names a product to move to.
"""
from __future__ import annotations

from datetime import timedelta
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
        how_often, per = _cadence_words(first)
        nudges.append({
            "id": f"duplicate_commitment_{first.id}",
            "rank": 0,  # a wrong number matters more than an optimisation
            "body": (
                f"“{first.label}” and “{second.label}” are both £{amount:,.2f} "
                f"{how_often} around {first.next_date:%-d %b}. If they're the same "
                f"payment, £{extra:,.2f}{per} is being counted twice."
            ),
            "detail": (
                f"{len(group)} confirmed commitments share an amount (£{amount:,.2f}), a "
                f"cadence ({how_often}) and a due date within "
                f"{DUPLICATE_DAY_TOLERANCE} days. That usually means the merchant changed "
                f"its bank descriptor, so the new one was detected while the old one stayed "
                f"confirmed. We don't merge them automatically because two genuinely "
                f"separate payments can look identical. Remove whichever is wrong on the "
                f"commitments page and safe-to-spend corrects itself."
            ),
            "source": None,
            "as_of": None,
        })

    nudges.extend(_card_payment_overlap(db, user))
    return sorted(nudges, key=lambda n: n["rank"])


def _cadence_words(rule) -> tuple[str, str]:
    """How often a commitment repeats, as words for the duplicate nudge:
    ("monthly", "/month"), ("yearly", "/year"), ("every 3 months", " every 3
    months") ... (T-12-12: it always said "/month")."""
    if rule.cadence == "weekly":
        return "weekly", "/week"
    if rule.cadence == "monthly":
        return "monthly", "/month"
    if rule.cadence == "every_n_months":
        months = rule.interval_months or 1
        if months == 12:
            return "yearly", "/year"
        words = "monthly" if months == 1 else f"every {months} months"
        return words, "/month" if months == 1 else f" {words}"
    days = rule.interval_days or 30
    return f"every {days} days", f" every {days} days"


def _money(value: Decimal) -> str:
    return f"£{value:,.2f}"


def _overlap_anchor(window, today) -> str:
    """A fixed point for the overlap nudge's id, so a dismissal lasts: a later
    window starts on a payday; the first starts today (it moves daily), so it
    ends the day before payday; with no payday it runs to the horizon, which
    moves too, so the month (eng-b on #236)."""
    from .card_payments import OVERLAP_HORIZON_DAYS
    if window.start != today:
        return window.start.isoformat()
    if window.end < today + timedelta(days=OVERLAP_HORIZON_DAYS):
        return window.end.isoformat()
    return today.strftime("%Y-%m")


def _card_payment_overlap(db: Session, user) -> list[dict]:
    """The first pay window where the user's planned card payments and the
    projected card bills overlap (T-12-4b, ux O-2/O-3): the aggregate figures
    and which one nilu counts. Facts only; dismissed in the browser."""
    from .card_payments import overlap_windows
    from .common import _today
    today = _today()
    for window, _ in overlap_windows(db, user, today):
        if not window.overlaps:
            continue
        larger = max(window.planned, window.projected)
        return [{
            "id": f"card_payment_overlap_{_overlap_anchor(window, today)}",
            "rank": 0,  # a number counted twice matters most
            "body": (f"Your planned card payments ({_money(window.planned)}) overlap your projected card "
                     f"bills ({_money(window.projected)}). nilu counts the larger, {_money(larger)}, once."),
            "detail": (f"Between {window.start:%-d %b} and {window.end:%-d %b}. Planned items you marked as a card "
                       "payment and the card repayments nilu projects pay the same cards, so only the larger "
                       "total counts in safe to spend and the forecast."),
            "source": None,
            "as_of": None,
        }]
    return []


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
