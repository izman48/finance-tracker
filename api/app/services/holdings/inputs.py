"""Engine inputs from the stored holdings (ADR-002, T-11-4).

An adapter over the existing `assets` and `liabilities` tables, read in the
request with the caller's key (amounts and names are DEK-encrypted, so
nothing here filters or sums in SQL). The rules are the ones the Wealth
projection has always used, so no figure moves for a user who does nothing:

- an asset grows at its own %, else the projection's default %, except a
  legacy asset-liability (stored negative), which defaults to 0%;
- kind, group, model and the investment flag come from the kind registry.
  An unknown asset type is held flat at its stored value; a liability of
  an unknown kind is still debt (fail closed: debt is never hidden or
  turned into an asset);
- its monthly contribution is its linked bill's amount while the bill is
  confirmed (T-11-3c), with the payments already due since the link started
  as `paid_contributions`; never also the legacy `monthly_contribution`,
  which counts only for an asset with no link;
- a liability follows its loan schedule when its repayment is a linked,
  confirmed commitment, and stays flat at today's balance when not
  (`liabilities.owed_on`).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Asset, CommitmentLink, CommitmentRule, CommitmentStatus, Liability
from app.services.analytics.common import _add_months, _d, _today
from app.services.liabilities import confirmed_commitment_ids, is_linked, owed_on

from .projection import HoldingInput, value_on
from .registry import kind_for


def holding_inputs(db: Session, user, today: date, default_growth_pct: Decimal) -> list[HoldingInput]:
    """Every holding the user has, as engine inputs."""
    return asset_inputs(db, user, default_growth_pct, today) + _liability_inputs(db, user, today)


def without_investments(holdings: list[HoldingInput], day: date) -> list[HoldingInput]:
    """The "Include investments" choice off: drops the investment kinds
    (registry `is_investment`, owner D1) and nothing else. An investment
    worth less than nothing on `day` is money owed, so it counts as Debt and
    stays (lead, 2026-10-15). Debt kinds are never investments (validator)."""
    def owed(h: HoldingInput) -> bool:
        value = value_on(h, day)
        return value is not None and value < 0
    return [h for h in holdings if not h.is_investment or owed(h)]


def paid_contributions(link_row: CommitmentLink, rule: CommitmentRule, today: date) -> tuple:
    """The bill's monthly payments due since the link started (on or after
    `created_on`, on or before today), at its current amount. Walked on the
    bill's monthly cycle in both directions from `next_date`, which may be
    stale (it only rolls forward on a commitments read or a skip). The
    engine keeps those after the valuation, within 90 days."""
    if rule.cadence != "monthly":
        return ()
    amount = _d(rule.amount)
    anchor, start = rule.next_date, link_row.created_on
    k = (start.year - anchor.year) * 12 + (start.month - anchor.month) - 1
    out = []
    while True:
        when = _add_months(anchor, k)
        if when > today:
            break
        if when >= start:
            out.append((when, amount))
        k += 1
    return tuple(out)


def _contribution(link_row: CommitmentLink | None, rules: dict, legacy, today: date) -> tuple[Decimal, tuple]:
    """(monthly contribution, paid contributions) for one asset."""
    if link_row is None:
        return _d(legacy), ()
    rule = rules.get(link_row.commitment_id)
    if rule is None or rule.status != CommitmentStatus.CONFIRMED.value:
        return Decimal(0), ()
    return _d(rule.amount), paid_contributions(link_row, rule, today)


def asset_inputs(db: Session, user, default_growth_pct: Decimal, today: date | None = None) -> list[HoldingInput]:
    """The `assets` rows only, for callers that need no liabilities."""
    today = today or _today()
    links = {
        row.asset_id: row
        for row in db.query(CommitmentLink).filter(
            CommitmentLink.user_id == user.id, CommitmentLink.asset_id.isnot(None),
        )
    }
    rules = {}
    if links:
        ids = [row.commitment_id for row in links.values()]
        rules = {r.id: r for r in db.query(CommitmentRule).filter(
            CommitmentRule.user_id == user.id, CommitmentRule.id.in_(ids),
        )}
    inputs = []
    for a in db.query(Asset).filter(Asset.user_id == user.id).order_by(Asset.created_at).all():
        kind = kind_for("assets", a.asset_type)
        is_debt = kind.is_debt
        if a.assumed_growth_pct is not None:
            pct = a.assumed_growth_pct
        else:
            pct = Decimal(0) if is_debt else default_growth_pct
        contribution, paid = _contribution(links.get(a.id), rules, a.monthly_contribution, today)
        inputs.append(HoldingInput(
            id=str(a.id), name=a.name, kind=a.asset_type, model=kind.model,
            group=kind.group, is_investment=kind.is_investment,
            valuations=tuple((v.valued_at, _d(v.value)) for v in a.valuations),
            growth_pct=pct, monthly_contribution=contribution, paid_contributions=paid,
            contribution_linked=a.id in links, is_debt=is_debt, source="assets",
        ))
    return inputs


def _liability_inputs(db: Session, user, today: date) -> list[HoldingInput]:
    confirmed = confirmed_commitment_ids(db, user.id)
    inputs = []
    for x in db.query(Liability).filter(Liability.user_id == user.id).order_by(Liability.created_at).all():
        linked = is_linked(x, confirmed)
        kind = kind_for("liabilities", x.kind)
        if kind.model == "amortisation":
            owed = lambda day, x=x, linked=linked: owed_on(x, today, day, linked)  # noqa: E731
        else:
            # An unknown kind: still money owed, at its entered balance.
            owed = lambda day, balance=x.balance: balance  # noqa: E731
        inputs.append(HoldingInput(
            id=str(x.id), name=x.lender, kind=x.kind, model=kind.model,
            group=kind.group, is_investment=kind.is_investment, is_debt=kind.is_debt,
            source="liabilities", owed_on=owed,
        ))
    return inputs
