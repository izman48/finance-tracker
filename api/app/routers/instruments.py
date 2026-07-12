"""Instrument search — public reference data for live-pricing an asset."""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import CurrentUser
from app.models import Instrument
from app.schemas import InstrumentSearchResult
from app.services.pricing import service as pricing_service

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("/search", response_model=list[InstrumentSearchResult])
def search(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    q: str = "",
) -> list[Instrument]:
    """Search providers (crypto always; equities if a market-data key is set)
    and upsert the hits so the client can link an asset by a stable id."""
    return pricing_service.search_instruments(db, q)
