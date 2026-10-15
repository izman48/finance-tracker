"""Manually tracked assets (ISAs, pensions, property …) and their valuations."""
import logging
import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.core.display_text import refuse_hidden
from app.core.database import get_db
from app.core.ownership import require_owned_account_ids
from app.core.security import CurrentUser
from app.models import Asset, AssetFlow, AssetValuation, CommitmentLink, CommitmentRule
from app.models.commitment_link import CONTRIBUTION
from app.schemas import (
    AssetCreate,
    AssetFlowCreate,
    AssetFlowResponse,
    AssetResponse,
    AssetUpdate,
    AssetValuationCreate,
    LinkedBill,
)
from app.schemas.holdings import ContributionRequest, ContributionResponse, LinkedCommitment
from app.services import analytics_service, holding_links
from app.services.holdings.inputs import asset_inputs
from app.services.holdings.projection import value_on
from app.services.holdings.registry import kind_for
from app.services.liabilities import mortgages_owed_by_property

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assets", tags=["assets"])

# Every net worth, projection and graph read projects each holding month by
# month, so the count is bounded at create (ADR-002 section 6). A
# check-then-act bound: nothing downstream relies on it.
HOLDINGS_PER_USER_MAX = 100
# The history graph walks every value of every holding (sec on #223), so the
# values per holding are bounded where they are added. An overwrite of a
# date that has a value is always allowed.
VALUATIONS_PER_ASSET_MAX = 1000


def _own_asset(db: Session, user_id, asset_id: uuid.UUID) -> Asset:
    asset = (
        db.query(Asset)
        .options(joinedload(Asset.valuations))
        .filter(Asset.id == asset_id, Asset.user_id == user_id)
        .first()
    )
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


@router.get("", response_model=list[AssetResponse])
def list_assets(current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> list[AssetResponse]:
    assets = (
        db.query(Asset)
        .options(joinedload(Asset.valuations))
        .filter(Asset.user_id == current_user.id)
        .order_by(Asset.created_at)
        .all()
    )
    rows = db.query(CommitmentLink).filter(
        CommitmentLink.user_id == current_user.id, CommitmentLink.asset_id.isnot(None),
    ).all()
    bills = {}
    if rows:
        bills = {r.id: r for r in db.query(CommitmentRule).filter(
            CommitmentRule.user_id == current_user.id, CommitmentRule.id.in_([row.commitment_id for row in rows]),
        )}
    links = {row.asset_id: (bills.get(row.commitment_id), row.commitment_created) for row in rows}
    today = analytics_service._today()
    values = {h.id: value_on(h, today) for h in asset_inputs(db, current_user, Decimal(0), today)}
    owed = mortgages_owed_by_property(db, current_user.id, today)
    return [
        AssetResponse.model_validate(a).model_copy(update={
            "linked_commitment": _bill(*links.get(a.id, (None, False))),
            "value_today": _pennies(values.get(str(a.id))),
            **_equity(a, _pennies(values.get(str(a.id))), owed.get(a.id)),
        })
        for a in assets
    ]


def _equity(asset: Asset, value: Decimal | None, owed: Decimal | None) -> dict:
    """A property with a mortgage: value today − what its mortgages owe
    (T-12-6b). Display only; it may be negative."""
    if asset.asset_type != "property" or value is None or owed is None:
        return {}
    owed = _pennies(owed)
    return {"mortgage_owed": owed, "equity": value - owed}


def _pennies(value: Decimal | None) -> Decimal | None:
    return None if value is None else value.quantize(Decimal("0.01"))


def _bill(rule: CommitmentRule | None, created: bool) -> LinkedBill | None:
    if rule is None:
        return None
    return LinkedBill(id=rule.id, label=rule.label, amount=rule.amount, next_date=rule.next_date,
                      pay_from_account_id=rule.account_id, created=created)


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
def create_asset(
    body: AssetCreate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Asset:
    held = db.query(Asset).filter(Asset.user_id == current_user.id).count()
    if held >= HOLDINGS_PER_USER_MAX:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"You can track up to {HOLDINGS_PER_USER_MAX} holdings. Delete one to add another.",
        )
    asset = Asset(
        user_id=current_user.id,
        name=body.name.strip(),
        asset_type=body.asset_type,
        assumed_growth_pct=body.assumed_growth_pct,
        monthly_contribution=body.monthly_contribution,
    )
    db.add(asset)
    db.flush()
    db.add(
        AssetValuation(
            asset_id=asset.id,
            value=body.value,
            valued_at=body.valued_at or analytics_service._today(),
        )
    )
    db.commit()
    db.refresh(asset)
    return asset


@router.patch("/{asset_id}", response_model=AssetResponse)
def update_asset(
    asset_id: uuid.UUID,
    body: AssetUpdate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Asset:
    asset = _own_asset(db, current_user.id, asset_id)
    if body.name is not None:
        if body.name.strip() != asset.name:
            refuse_hidden("name", body.name)
        asset.name = body.name.strip()
    if body.asset_type is not None:
        asset.asset_type = body.asset_type
    # exclude_unset: "field absent" leaves the assumption alone, an explicit
    # null clears it back to the projection default.
    updates = body.model_dump(exclude_unset=True)
    if asset.commitment_link is not None:
        _refuse_unlinking_edit(asset, updates)
    if "assumed_growth_pct" in updates:
        asset.assumed_growth_pct = body.assumed_growth_pct
    if "monthly_contribution" in updates:
        asset.monthly_contribution = body.monthly_contribution
    db.commit()
    db.refresh(asset)
    return asset


def _refuse_unlinking_edit(asset: Asset, updates: dict) -> None:
    """A linked holding's contribution is its bill: no legacy figure beside
    it, and no change to a kind that can't carry one (opt out first)."""
    kind = kind_for("assets", updates.get("asset_type") or asset.asset_type)
    if updates.get("monthly_contribution") is not None or kind.link_role != CONTRIBUTION:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This holding's contribution is a linked bill. Change or stop it under Monthly contribution.",
        )


@router.put("/{asset_id}/contribution", response_model=ContributionResponse)
def set_contribution(
    asset_id: uuid.UUID,
    body: ContributionRequest,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> ContributionResponse:
    """Opt in to a monthly contribution as a linked bill, or change it."""
    asset = _own_asset(db, current_user.id, asset_id)
    if kind_for("assets", asset.asset_type).link_role != CONTRIBUTION:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Only an investment can have a monthly contribution.")
    require_owned_account_ids(db, current_user, body)
    rule = holding_links.linked_rule(db, asset)
    if rule is not None:
        holding_links.sync(rule, body.amount, body.next_date, body.pay_from_account_id)
        result = "updated"
    else:
        asset.commitment_link = None  # a row left by a deleted bill
        try:
            rule, result = holding_links.link(db, asset, body.commitment_choice, body.amount, body.next_date,
                                              analytics_service._today(), body.pay_from_account_id)
        except holding_links.ChooseCommitment as exc:
            db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_choose(exc.candidates)) from None
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="That bill was just linked to something else. Reload and try again.") from None
    return ContributionResponse(linked_commitment=LinkedCommitment(id=rule.id, label=rule.label), link_result=result)


def _choose(options: list[CommitmentRule]) -> dict:
    return {
        "code": "choose_commitment",
        "message": "You already have a bill that could be this contribution. Choose it, or add a new one.",
        "candidates": [
            {"id": str(r.id), "label": r.label, "amount": str(r.amount), "cadence": r.cadence,
             "next_date": r.next_date.isoformat()}
            for r in options
        ],
    }


@router.delete("/{asset_id}/contribution")
def stop_contribution(
    asset_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    """Opt out: unlink, keeping today's value (contributions included)."""
    asset = _own_asset(db, current_user.id, asset_id)
    if asset.commitment_link is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No linked contribution")
    today = analytics_service._today()
    holding = next(h for h in asset_inputs(db, current_user, Decimal(0), today) if h.id == str(asset.id))
    holding_links.remove(db, asset, value_on(holding, today), today)
    db.commit()
    return {"message": "Contribution stopped"}


@router.delete("/{asset_id}")
def delete_asset(
    asset_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    db.delete(_own_asset(db, current_user.id, asset_id))
    db.commit()
    return {"message": "Asset deleted"}


@router.post("/{asset_id}/valuations", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
def add_valuation(
    asset_id: uuid.UUID,
    body: AssetValuationCreate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Asset:
    """Record a new value for the asset (same-date entries overwrite)."""
    asset = _own_asset(db, current_user.id, asset_id)
    valued_at = body.valued_at or analytics_service._today()

    existing = (
        db.query(AssetValuation)
        .filter(AssetValuation.asset_id == asset.id, AssetValuation.valued_at == valued_at)
        .first()
    )
    if existing:
        existing.value = body.value
    elif len(asset.valuations) >= VALUATIONS_PER_ASSET_MAX:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This holding has {VALUATIONS_PER_ASSET_MAX} values already. Delete an old one to add another.",
        )
    else:
        db.add(AssetValuation(asset_id=asset.id, value=body.value, valued_at=valued_at))
    db.commit()
    db.refresh(asset)
    return asset


@router.delete("/{asset_id}/valuations/{valuation_id}")
def delete_valuation(
    asset_id: uuid.UUID,
    valuation_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    asset = _own_asset(db, current_user.id, asset_id)
    valuation = (
        db.query(AssetValuation)
        .filter(AssetValuation.id == valuation_id, AssetValuation.asset_id == asset.id)
        .first()
    )
    if not valuation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Valuation not found")
    db.delete(valuation)
    db.commit()
    return {"message": "Valuation deleted"}


@router.post("/{asset_id}/flows", response_model=AssetFlowResponse, status_code=status.HTTP_201_CREATED)
def add_flow(
    asset_id: uuid.UUID,
    body: AssetFlowCreate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> AssetFlow:
    """Record money added to (+) or withdrawn from (−) the asset, so the
    contribution-vs-growth decomposition can tell saving from markets."""
    asset = _own_asset(db, current_user.id, asset_id)
    if body.amount == 0:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Flow amount can't be zero")
    flow = AssetFlow(
        asset_id=asset.id,
        amount=body.amount,
        flow_date=body.flow_date or analytics_service._today(),
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)
    return flow


@router.delete("/{asset_id}/flows/{flow_id}")
def delete_flow(
    asset_id: uuid.UUID,
    flow_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    asset = _own_asset(db, current_user.id, asset_id)
    flow = (
        db.query(AssetFlow)
        .filter(AssetFlow.id == flow_id, AssetFlow.asset_id == asset.id)
        .first()
    )
    if not flow:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Flow not found")
    db.delete(flow)
    db.commit()
    return {"message": "Flow deleted"}
