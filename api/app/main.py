from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers import (
    health_router,
    auth_router,
    banking_router,
    analytics_router,
    rules_router,
    assets_router,
)

settings = get_settings()

app = FastAPI(
    title="Finance Tracker API",
    description="Personal finance insights from Open Banking data",
    version="0.1.0",
    docs_url="/api/docs" if settings.environment != "production" else None,
    redoc_url="/api/redoc" if settings.environment != "production" else None,
)

# CORS middleware - restrict in production
origins = (
    ["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"]
    if settings.environment == "development"
    else []
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(banking_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(rules_router, prefix="/api/v1")
app.include_router(assets_router, prefix="/api/v1")


@app.get("/")
def root():
    """Root endpoint - redirect to docs."""
    return {"message": "Finance Tracker API", "docs": "/api/docs"}
