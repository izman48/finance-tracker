from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
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
def health_check(response: Response, db: Annotated[Session, Depends(get_db)]) -> HealthResponse:
    """Verifies the API is running and the database answers.

    503 when the database is down (T-12-10b), so a load balancer or uptime
    check sees it, with the same fixed body: never the driver's error text,
    host or port.
    """
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", database="unhealthy")
    return HealthResponse(status="healthy", database="healthy")
