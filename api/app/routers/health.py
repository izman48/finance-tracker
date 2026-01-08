from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    database: str


@router.get("/health", response_model=HealthResponse)
def health_check(db: Annotated[Session, Depends(get_db)]) -> HealthResponse:
    """
    Health check endpoint.
    
    Verifies API is running and database is accessible.
    """
    # Check database connection
    try:
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception:
        db_status = "unhealthy"

    return HealthResponse(
        status="healthy" if db_status == "healthy" else "degraded",
        database=db_status,
    )
