from app.routers.health import router as health_router
from app.routers.auth import router as auth_router
from app.routers.banking import router as banking_router

__all__ = ["health_router", "auth_router", "banking_router"]
