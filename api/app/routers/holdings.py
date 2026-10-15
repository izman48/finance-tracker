"""Holdings read routes (ADR-002). Web session only, read-only."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import CurrentUser
from app.schemas import InvestmentGraph
from app.services.holdings.graphs import investment_graph
from app.services.holdings.projection import MAX_MONTHS

router = APIRouter(prefix="/holdings", tags=["holdings"])


@router.get("/projection", response_model=InvestmentGraph)
def get_investment_projection(
    current_user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
    months: Annotated[int, Query(ge=1, le=MAX_MONTHS)] = 120,
    holding_id: uuid.UUID | None = None,
) -> InvestmentGraph:
    """Each investment and their total: entered valuations, then the
    holding engine's forecast (the target projection's function) with what
    is paid in. `holding_id` narrows it to one of the caller's investments;
    any other id is 404. An estimate from the user's own %, not advice."""
    graph = investment_graph(db, current_user, months, str(holding_id) if holding_id else None)
    if graph is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Investment not found")
    return InvestmentGraph(**graph)
