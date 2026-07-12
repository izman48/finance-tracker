from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.security import set_session_dek
from app.core.user_crypto import DEKUnavailableError
from app.routers import (
    health_router,
    auth_router,
    banking_router,
    analytics_router,
    rules_router,
    assets_router,
    instruments_router,
)

settings = get_settings()

app = FastAPI(
    title="Finance Tracker API",
    description="Personal finance insights from Open Banking data",
    version="0.1.0",
    docs_url="/api/docs" if settings.environment != "production" else None,
    redoc_url="/api/redoc" if settings.environment != "production" else None,
    # Unwraps the per-user data-encryption key from the bearer token into the
    # request context on every request (no-op when absent).
    dependencies=[Depends(set_session_dek)],
)


@app.exception_handler(DEKUnavailableError)
async def dek_unavailable_handler(request: Request, exc: DEKUnavailableError):
    """Touched encrypted data without a session key: the token predates
    per-user encryption. A fresh login mints one, so ask for that."""
    return JSONResponse(
        status_code=401,
        content={"detail": str(exc)},
        headers={"WWW-Authenticate": "Bearer"},
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
app.include_router(instruments_router, prefix="/api/v1")


@app.get("/")
def root():
    """Root endpoint - redirect to docs."""
    return {"message": "Finance Tracker API", "docs": "/api/docs"}
