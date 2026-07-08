"""Net worth: manual-asset totals and the reconstructed history series."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import AccountRole, Asset, AssetFlow, Transaction

from .common import _add_months, _d, _load, _today, resolve_roles


def assets_total(db: Session, user, as_of: date | None = None) -> Decimal:
    """Sum of each manual asset's most recent valuation on/before as_of."""
    assets = db.query(Asset).filter(Asset.user_id == user.id).all()
    total = Decimal(0)
    for asset in assets:
        current = None
        for v in asset.valuations:  # ordered by valued_at
            if as_of is None or v.valued_at <= as_of:
                current = v.value
        if current is not None:
            total += _d(current)
    return total


def asset_decomposition(db: Session, user, months: int = 12) -> dict:
    """Contribution-vs-growth split of the manual-asset movement over a window.

    growth = Δvaluation − Σrecorded flows. An asset first valued *inside* the
    window is measured from its first sighting — coming into tracking is
    neither saving nor growth. The split is only as good as the flows the user
    records (an unrecorded deposit reads as growth), which the UI says out
    loud. Bank-account movement is deliberately out of scope — cash moving
    isn't market growth, and the ledger already explains it.
    """
    today = _today()
    start = _add_months(today, -months)

    assets = db.query(Asset).filter(Asset.user_id == user.id).all()
    assets_start = Decimal(0)
    assets_end = Decimal(0)
    # Per-asset baseline date: window start, or first sighting if later.
    baseline_date: dict = {}
    for asset in assets:
        if not asset.valuations:
            continue
        at_start = None
        for v in asset.valuations:  # ordered by valued_at
            if v.valued_at <= start:
                at_start = v.value
        assets_end += _d(asset.valuations[-1].value)
        if at_start is not None:
            assets_start += _d(at_start)
            baseline_date[asset.id] = start
        else:
            first = asset.valuations[0]
            assets_start += _d(first.value)
            baseline_date[asset.id] = first.valued_at

    # Flows after each asset's baseline. Amounts are encrypted — scope by the
    # user's assets in SQL, filter/sum in Python.
    rows = (
        db.query(AssetFlow)
        .join(Asset, AssetFlow.asset_id == Asset.id)
        .filter(
            Asset.user_id == user.id,
            AssetFlow.flow_date > start,
            AssetFlow.flow_date <= today,
        )
        .all()
    )
    counted = [f for f in rows if f.asset_id in baseline_date and f.flow_date > baseline_date[f.asset_id]]
    contributions = sum((_d(f.amount) for f in counted), Decimal(0))
    delta = assets_end - assets_start

    return {
        "start_date": start,
        "end_date": today,
        "assets_start": assets_start,
        "assets_end": assets_end,
        "assets_delta": delta,
        "contributions": contributions,
        "growth": delta - contributions,
        "flows_recorded": len(counted),
    }


def net_worth_history(db: Session, user, months: int = 12) -> list[dict]:
    """Net worth at month-ends (plus today), looking back `months` months.

    Bank balances are reconstructed by walking transactions backwards from the
    current balance; manual assets contribute their latest valuation on/before
    each date.
    """
    accounts, settings = _load(db, user)
    roles = resolve_roles(accounts, settings)
    today = _today()

    points: list[date] = [today]
    cursor = date(today.year, today.month, 1) - timedelta(days=1)
    for _ in range(months):
        points.append(cursor)
        cursor = date(cursor.year, cursor.month, 1) - timedelta(days=1)
    points = sorted(set(points))
    earliest = datetime.combine(points[0], datetime.min.time(), tzinfo=timezone.utc)

    bank_at: dict[date, Decimal] = {p: Decimal(0) for p in points}
    for acc in accounts:
        role = roles[acc.id]
        if role == AccountRole.EXCLUDED:
            continue
        txs = (
            db.query(Transaction.transaction_date, Transaction.transaction_type, Transaction.amount)
            .filter(Transaction.account_id == acc.id, Transaction.transaction_date > earliest)
            .all()
        )
        for p in points:
            # Net signed flow after p: inflows positive, outflows negative.
            delta_after = sum(
                (
                    _d(amount) if getattr(ttype, "value", ttype) == "credit" else -_d(amount)
                    for tx_date, ttype, amount in txs
                    if tx_date.date() > p
                ),
                Decimal(0),
            )
            if role == AccountRole.CREDIT:
                # Owed grows with spending (debits): owed(p) = owed_now + delta_after.
                owed_at = abs(_d(acc.current_balance)) + delta_after
                bank_at[p] -= max(owed_at, Decimal(0))
            else:
                bank_at[p] += _d(acc.current_balance) - delta_after

    out = []
    for p in points:
        assets_at = assets_total(db, user, as_of=p)
        out.append(
            {
                "date": p.isoformat(),
                "bank": bank_at[p],
                "assets": assets_at,
                "net_worth": bank_at[p] + assets_at,
            }
        )
    return out
