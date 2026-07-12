"""Manually tracked assets (ISAs, pensions, property …) and their valuations."""
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.database import get_db
from app.core.security import CurrentUser
from app.models import Asset, AssetFlow, AssetValuation, Instrument
from app.schemas import (
    AssetCreate,
    AssetFlowCreate,
    AssetFlowResponse,
    AssetLink,
    AssetResponse,
    AssetUpdate,
    AssetValuationCreate,
)
from app.services import analytics_service
from app.services.pricing import service as pricing_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assets", tags=["assets"])


def _own_asset(db: Session, user_id, asset_id: str) -> Asset:
    try:
        aid = uuid.UUID(str(asset_id))
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    asset = (
        db.query(Asset)
        .options(joinedload(Asset.valuations))
        .filter(Asset.id == aid, Asset.user_id == user_id)
        .first()
    )
    if not asset:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


def _with_price(db: Session, asset: Asset) -> Asset:
    """Attach the latest cached unit price as transient attributes so the
    response serialiser (from_attributes) can surface it. Not persisted."""
    if asset.instrument_id:
        p = pricing_service.latest_price(db, asset.instrument_id)
        asset.unit_price_gbp = p.price_gbp if p else None
        asset.priced_at = p.as_of if p else None
    else:
        asset.unit_price_gbp = None
        asset.priced_at = None
    return asset


@router.get("", response_model=list[AssetResponse])
def list_assets(current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> list[Asset]:
    assets = (
        db.query(Asset)
        .options(joinedload(Asset.valuations))
        .filter(Asset.user_id == current_user.id)
        .order_by(Asset.created_at)
        .all()
    )
    return [_with_price(db, a) for a in assets]


@router.post("/refresh-prices", response_model=list[AssetResponse])
def refresh_prices(current_user: CurrentUser, db: Annotated[Session, Depends(get_db)]) -> list[Asset]:
    """Reprice every linked asset and snapshot today's value into a valuation,
    then return the balance sheet. Called on Wealth load, before history."""
    pricing_service.price_and_snapshot(db, current_user)
    assets = (
        db.query(Asset)
        .options(joinedload(Asset.valuations))
        .filter(Asset.user_id == current_user.id)
        .order_by(Asset.created_at)
        .all()
    )
    return [_with_price(db, a) for a in assets]


@router.post("/{asset_id}/link", response_model=AssetResponse)
def link_instrument(
    asset_id: str,
    body: AssetLink,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Asset:
    """Link a manual asset to a live-priced instrument and set units held.
    Immediately snapshots a live valuation so the balance sheet updates."""
    asset = _own_asset(db, current_user.id, asset_id)
    instrument = db.query(Instrument).filter(Instrument.id == body.instrument_id).first()
    if instrument is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instrument not found")
    asset.instrument_id = instrument.id
    asset.units = body.units
    db.commit()
    pricing_service.price_and_snapshot(db, current_user)
    db.refresh(asset)
    return _with_price(db, asset)


@router.post("/{asset_id}/unlink", response_model=AssetResponse)
def unlink_instrument(
    asset_id: str,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Asset:
    """Stop live-pricing an asset (its valuation history is kept — it just
    goes back to manual updates)."""
    asset = _own_asset(db, current_user.id, asset_id)
    asset.instrument_id = None
    asset.units = None
    db.commit()
    db.refresh(asset)
    return _with_price(db, asset)


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
def create_asset(
    body: AssetCreate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Asset:
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
    return _with_price(db, asset)


@router.patch("/{asset_id}", response_model=AssetResponse)
def update_asset(
    asset_id: str,
    body: AssetUpdate,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> Asset:
    asset = _own_asset(db, current_user.id, asset_id)
    if body.name is not None:
        asset.name = body.name.strip()
    if body.asset_type is not None:
        asset.asset_type = body.asset_type
    # exclude_unset: "field absent" leaves the assumption alone, an explicit
    # null clears it back to the projection default.
    updates = body.model_dump(exclude_unset=True)
    if "assumed_growth_pct" in updates:
        asset.assumed_growth_pct = body.assumed_growth_pct
    if "monthly_contribution" in updates:
        asset.monthly_contribution = body.monthly_contribution
    db.commit()
    db.refresh(asset)
    return _with_price(db, asset)


@router.delete("/{asset_id}")
def delete_asset(
    asset_id: str,
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    db.delete(_own_asset(db, current_user.id, asset_id))
    db.commit()
    return {"message": "Asset deleted"}


@router.post("/{asset_id}/valuations", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
def add_valuation(
    asset_id: str,
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
    else:
        db.add(AssetValuation(asset_id=asset.id, value=body.value, valued_at=valued_at))
    db.commit()
    db.refresh(asset)
    return _with_price(db, asset)


@router.delete("/{asset_id}/valuations/{valuation_id}")
def delete_valuation(
    asset_id: str,
    valuation_id: str,
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
    asset_id: str,
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
    asset_id: str,
    flow_id: str,
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
